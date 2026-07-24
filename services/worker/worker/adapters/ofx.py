"""Deterministic OFX/QFX bank and credit-card statement adapter.

The parser intentionally supports the common statement subset shared by OFX 1
(SGML) and OFX 2 (XML).  It does not try to repair arbitrary SGML: every
transaction must be contained in a ``STMTTRN`` block and have the identity and
money fields required by the ledger.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from decimal import Decimal

from worker.adapters.base import AdapterError, parse_decimal
from worker.models import (
    AccountKind,
    Direction,
    ParsedFile,
    ParsedTransaction,
    ParseResult,
    StatementMetadata,
)

_HEADER = re.compile(r"\A(?:[A-Z][A-Z0-9-]*:[^\r\n]*\r?\n)+\s*", re.IGNORECASE)
_TRANSACTION = re.compile(r"<STMTTRN\b[^>]*>(.*?)</STMTTRN\s*>", re.IGNORECASE | re.DOTALL)
_BANK_STATEMENT = re.compile(r"<STMTRS\b", re.IGNORECASE)
_CARD_STATEMENT = re.compile(r"<CCSTMTRS\b", re.IGNORECASE)
_INVESTMENT = re.compile(r"<(?:INVSTMTRS|INVSTMTMSGSRSV1)\b", re.IGNORECASE)
_TAG_CACHE: dict[str, re.Pattern[str]] = {}


class OfxAdapter:
    format = "ofx"
    name = "ofx_qfx"

    def detect(self, file: ParsedFile) -> float:
        if file.extension not in {".ofx", ".qfx"}:
            return 0.0
        try:
            text = _decode(file.content)
        except UnicodeDecodeError:
            return 0.0
        if re.search(r"<OFX\b", text, re.IGNORECASE):
            return 0.99
        return 0.2

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> ParseResult:
        text = _decode(file.content)
        document = _HEADER.sub("", text, count=1).strip()
        if not re.search(r"<OFX\b", document, re.IGNORECASE):
            raise AdapterError("OFX document root is missing")
        if _INVESTMENT.search(document):
            raise AdapterError("OFX investment statements are unsupported")

        bank_count = len(_BANK_STATEMENT.findall(document))
        card_count = len(_CARD_STATEMENT.findall(document))
        if bank_count + card_count != 1:
            raise AdapterError("OFX file must contain exactly one bank or credit-card statement")
        document_kind = AccountKind.CREDIT_CARD if card_count else AccountKind.CHEQUING
        if document_kind is AccountKind.CREDIT_CARD and account_kind is not AccountKind.CREDIT_CARD:
            raise AdapterError("credit-card OFX cannot be imported into an asset account")
        if document_kind is not AccountKind.CREDIT_CARD and not account_kind.is_asset:
            raise AdapterError("bank OFX cannot be imported into a credit-card account")

        currency = (_tag_value(document, "CURDEF") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise AdapterError("OFX statement currency is missing or invalid")
        account_id = _tag_value(document, "ACCTID")
        if account_id is None:
            raise AdapterError("OFX account identity is missing")
        account_digits = re.sub(r"\D", "", account_id)
        if len(account_digits) < 4:
            raise AdapterError("OFX account identity cannot be safely matched")

        start = _ofx_date(_required_tag(document, "DTSTART"))
        end = _ofx_date(_required_tag(document, "DTEND"))
        closing = parse_decimal(_required_tag(document, "BALAMT"))
        if document_kind is AccountKind.CREDIT_CARD:
            # OFX card balances and transaction amounts follow account-ledger
            # polarity (charges are negative). Ledger stores card debt as positive.
            closing = -closing

        transactions: list[ParsedTransaction] = []
        fitids: set[str] = set()
        for block in _TRANSACTION.findall(document):
            fitid = _required_tag(block, "FITID").strip()
            if not fitid:
                raise AdapterError("OFX FITID cannot be blank")
            if fitid in fitids:
                raise AdapterError("OFX contains duplicate FITID values")
            fitids.add(fitid)

            ofx_amount = parse_decimal(_required_tag(block, "TRNAMT"))
            amount = -ofx_amount if document_kind is AccountKind.CREDIT_CARD else ofx_amount
            transaction_type = (_tag_value(block, "TRNTYPE") or "OTHER").strip().upper()
            description = _description(block)
            direction = _direction(
                transaction_type=transaction_type,
                amount=amount,
                account_kind=account_kind,
            )
            transactions.append(
                ParsedTransaction(
                    booked_date=_ofx_date(_required_tag(block, "DTPOSTED")),
                    description_raw=description,
                    amount_native=amount,
                    currency_native=currency,
                    external_ref=fitid,
                    direction=direction,
                    enrichment={"ofx_transaction_type": transaction_type},
                )
            )
        if not transactions:
            raise AdapterError("OFX statement contains no transactions")

        return ParseResult(
            adapter=self.name,
            rows=tuple(transactions),
            statement=StatementMetadata(
                period_start=start,
                period_end=end,
                closing_balance=closing,
                currency=currency,
                account_ref_masked=f"••••{account_digits[-4:]}",
            ),
        )


def _decode(content: bytes) -> str:
    # OFX 1 headers often declare an encoding inconsistently. UTF-8 and the
    # Windows-1252-compatible latin-1 range cover the interoperable text subset.
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def _tag_pattern(tag: str) -> re.Pattern[str]:
    normalized = tag.upper()
    pattern = _TAG_CACHE.get(normalized)
    if pattern is None:
        pattern = re.compile(
            rf"<{re.escape(normalized)}\b[^>]*>\s*([^<\r\n]+)",
            re.IGNORECASE,
        )
        _TAG_CACHE[normalized] = pattern
    return pattern


def _tag_value(value: str, tag: str) -> str | None:
    match = _tag_pattern(tag).search(value)
    return html.unescape(match.group(1).strip()) if match is not None else None


def _required_tag(value: str, tag: str) -> str:
    resolved = _tag_value(value, tag)
    if resolved is None or not resolved.strip():
        raise AdapterError(f"OFX {tag} is missing")
    return resolved


def _ofx_date(value: str) -> date:
    # Dates are YYYYMMDDHHMMSS with optional fractional seconds and zone suffix.
    match = re.match(r"^(\d{8})", value.strip())
    if match is None:
        raise AdapterError(f"invalid OFX date: {value!r}")
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError as exc:
        raise AdapterError(f"invalid OFX date: {value!r}") from exc


def _description(block: str) -> str:
    parts = [
        part.strip()
        for tag in ("NAME", "MEMO")
        if (part := _tag_value(block, tag)) is not None and part.strip()
    ]
    if not parts:
        raise AdapterError("OFX transaction description is missing")
    return " — ".join(dict.fromkeys(parts))


def _direction(*, transaction_type: str, amount: Decimal, account_kind: AccountKind) -> Direction:
    if transaction_type in {"FEE", "SRVCHG"}:
        return Direction.FEE
    if transaction_type == "INT" and account_kind is AccountKind.CREDIT_CARD:
        return Direction.INTEREST
    if transaction_type in {"PAYMENT", "DIRECTDEBIT"} and account_kind is AccountKind.CREDIT_CARD:
        return Direction.PAYMENT
    if account_kind is AccountKind.CREDIT_CARD and amount < 0:
        return Direction.REFUND
    return Direction.CREDIT if amount > 0 and account_kind.is_asset else Direction.DEBIT
