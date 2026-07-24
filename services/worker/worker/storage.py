"""S3-compatible raw-statement access (MinIO in the local stack)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from hmac import compare_digest
from typing import Protocol

import boto3
from botocore.config import Config
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STATEMENT_ENVELOPE_MAGIC = b"LEDGER01"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class StatementEnvelopeError(ValueError):
    """Raised when an encrypted source object cannot be authenticated."""


class ObjectStore(Protocol):
    def read(self, key: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class S3Settings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    statement_encryption_key: bytes = field(repr=False)
    region: str = "us-east-1"
    force_path_style: bool = True

    @classmethod
    def from_env(cls) -> S3Settings:
        return cls(
            endpoint=_required_env("S3_ENDPOINT"),
            access_key=_required_env("S3_ACCESS_KEY"),
            secret_key=_required_env("S3_SECRET_KEY"),
            bucket=_required_env("S3_BUCKET"),
            statement_encryption_key=parse_statement_encryption_key(
                _required_exact_env("STATEMENT_ENCRYPTION_KEY")
            ),
            region=os.getenv("S3_REGION", "us-east-1"),
            force_path_style=os.getenv("S3_FORCE_PATH_STYLE", "true").lower()
            in {"1", "true", "yes"},
        )


class S3ObjectStore:
    def __init__(self, settings: S3Settings) -> None:
        addressing_style = "path" if settings.force_path_style else "virtual"
        self._bucket = settings.bucket
        self._statement_encryption_key = settings.statement_encryption_key
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            region_name=settings.region,
            config=Config(s3={"addressing_style": addressing_style}),
        )

    @classmethod
    def from_env(cls) -> S3ObjectStore:
        return cls(S3Settings.from_env())

    def read(self, key: str) -> bytes:
        if not key.strip():
            raise ValueError("object key cannot be blank")
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response["Body"]
        try:
            encrypted = bytes(body.read())
        finally:
            body.close()
        return decrypt_statement_bytes(encrypted, self._statement_encryption_key)


class MemoryObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = dict(objects)

    def read(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


def _required_exact_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


def parse_statement_encryption_key(value: str) -> bytes:
    if _KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("STATEMENT_ENCRYPTION_KEY must be exactly 64 hexadecimal characters")
    return bytes.fromhex(value)


def decrypt_statement_bytes(envelope: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("statement encryption requires a 32-byte key")
    header_bytes = len(STATEMENT_ENVELOPE_MAGIC) + _NONCE_BYTES + _TAG_BYTES
    if len(envelope) < header_bytes:
        raise StatementEnvelopeError("invalid encrypted statement envelope")
    magic = envelope[: len(STATEMENT_ENVELOPE_MAGIC)]
    if not compare_digest(magic, STATEMENT_ENVELOPE_MAGIC):
        raise StatementEnvelopeError("unsupported encrypted statement envelope")
    nonce_start = len(STATEMENT_ENVELOPE_MAGIC)
    tag_start = nonce_start + _NONCE_BYTES
    ciphertext_start = tag_start + _TAG_BYTES
    nonce = envelope[nonce_start:tag_start]
    tag = envelope[tag_start:ciphertext_start]
    ciphertext = envelope[ciphertext_start:]
    try:
        return AESGCM(key).decrypt(
            nonce,
            ciphertext + tag,
            STATEMENT_ENVELOPE_MAGIC,
        )
    except InvalidTag as exc:
        raise StatementEnvelopeError("encrypted statement authentication failed") from exc
