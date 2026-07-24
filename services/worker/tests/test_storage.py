from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from worker.storage import (
    STATEMENT_ENVELOPE_MAGIC,
    S3ObjectStore,
    S3Settings,
    StatementEnvelopeError,
    decrypt_statement_bytes,
    parse_statement_encryption_key,
)

KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"


def encrypted_envelope(plaintext: bytes, *, key: bytes | None = None) -> bytes:
    encryption_key = key or bytes.fromhex(KEY_HEX)
    nonce = bytes(range(12))
    encrypted = AESGCM(encryption_key).encrypt(nonce, plaintext, STATEMENT_ENVELOPE_MAGIC)
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    return STATEMENT_ENVELOPE_MAGIC + nonce + tag + ciphertext


def test_decrypts_versioned_aes_256_gcm_envelope() -> None:
    plaintext = b"private synthetic statement"
    envelope = encrypted_envelope(plaintext)

    assert envelope[:8] == b"LEDGER01"
    assert decrypt_statement_bytes(envelope, bytes.fromhex(KEY_HEX)) == plaintext


@pytest.mark.parametrize(
    "invalid",
    ["", "00" * 31, "00" * 33, "g0" * 32, f" {KEY_HEX}"],
)
def test_encryption_key_requires_exactly_64_hex_characters(invalid: str) -> None:
    with pytest.raises(ValueError, match="exactly 64 hexadecimal"):
        parse_statement_encryption_key(invalid)


def test_envelope_rejects_wrong_version_truncation_and_tampering() -> None:
    key = bytes.fromhex(KEY_HEX)
    valid = encrypted_envelope(b"statement")
    wrong_version = b"LEDGER02" + valid[8:]
    tampered = valid[:-1] + bytes([valid[-1] ^ 1])

    with pytest.raises(StatementEnvelopeError, match="unsupported"):
        decrypt_statement_bytes(wrong_version, key)
    with pytest.raises(StatementEnvelopeError, match="invalid"):
        decrypt_statement_bytes(b"LEDGER01", key)
    with pytest.raises(StatementEnvelopeError, match="authentication"):
        decrypt_statement_bytes(tampered, key)


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.closed = False

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        self.closed = True


class _S3Client:
    def __init__(self, body: _Body) -> None:
        self.body = body

    def get_object(self, **_kwargs: object) -> dict[str, _Body]:
        return {"Body": self.body}


def test_s3_store_decrypts_authenticated_object_before_returning(monkeypatch) -> None:
    plaintext = b"Date,Description,Amount\n2026-01-01,Synthetic,1.00\n"
    body = _Body(encrypted_envelope(plaintext))
    client = _S3Client(body)
    monkeypatch.setattr("worker.storage.boto3.client", lambda *_args, **_kwargs: client)
    settings = S3Settings(
        endpoint="http://minio:9000",
        access_key="test",
        secret_key="test",
        bucket="statements",
        statement_encryption_key=bytes.fromhex(KEY_HEX),
    )

    store = S3ObjectStore(replace(settings))

    assert store.read("source.csv") == plaintext
    assert body.closed is True
