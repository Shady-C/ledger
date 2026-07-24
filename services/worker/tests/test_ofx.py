from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from worker.adapters.base import AdapterError
from worker.adapters.ofx import OfxAdapter
from worker.models import AccountKind, Direction, ParsedFile
from worker.pipeline import IngestionPipeline
from worker.repository import InMemoryRepository
from worker.storage import MemoryObjectStore


def test_ofx1_credit_card_uses_fitid_and_inverts_account_ledger_signs() -> None:
    content = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII

<OFX>
<CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS>
<CURDEF>CAD
<CCACCTFROM><ACCTID>9999888877771234
<BANKTRANLIST><DTSTART>20260101000000<DTEND>20260131235959
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260103<TRNAMT>-150.00<FITID>CARD-1
<NAME>Synthetic Hotel</STMTTRN>
<STMTTRN><TRNTYPE>PAYMENT<DTPOSTED>20260120<TRNAMT>25.00<FITID>CARD-2
<NAME>Payment Thank You</STMTTRN>
<LEDGERBAL><BALAMT>-125.00<DTASOF>20260131
</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""

    result = OfxAdapter().parse(
        ParsedFile(name="card.qfx", content=content),
        account_kind=AccountKind.CREDIT_CARD,
    )

    assert result.statement.period_start == date(2026, 1, 1)
    assert result.statement.closing_balance == Decimal("125.00")
    assert result.statement.account_ref_masked == "••••1234"
    assert [(row.external_ref, row.amount_native, row.direction) for row in result.rows] == [
        ("CARD-1", Decimal("150.00"), Direction.DEBIT),
        ("CARD-2", Decimal("-25.00"), Direction.PAYMENT),
    ]


def test_ofx2_bank_statement_preserves_asset_ledger_signs() -> None:
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD</CURDEF><BANKACCTFROM><BANKID>001</BANKID><ACCTID>12345678</ACCTID>
</BANKACCTFROM><BANKTRANLIST><DTSTART>20260201000000</DTSTART>
<DTEND>20260228235959</DTEND>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260202</DTPOSTED>
<TRNAMT>200.00</TRNAMT><FITID>BANK-1</FITID><NAME>Salary</NAME></STMTTRN>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260203</DTPOSTED>
<TRNAMT>-50.00</TRNAMT><FITID>BANK-2</FITID><MEMO>Cash withdrawal</MEMO></STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>1150.00</BALAMT></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""

    result = OfxAdapter().parse(
        ParsedFile(name="bank.ofx", content=content),
        account_kind=AccountKind.SAVINGS,
    )

    assert result.statement.currency == "USD"
    assert result.statement.closing_balance == Decimal("1150.00")
    assert [(row.amount_native, row.direction) for row in result.rows] == [
        (Decimal("200.00"), Direction.CREDIT),
        (Decimal("-50.00"), Direction.DEBIT),
    ]


def test_ofx_rejects_investment_statements_and_account_kind_mismatch() -> None:
    investment = ParsedFile(
        name="portfolio.ofx",
        content=b"<OFX><INVSTMTMSGSRSV1><INVSTMTRS></INVSTMTRS></INVSTMTMSGSRSV1></OFX>",
    )
    with pytest.raises(AdapterError, match="investment"):
        OfxAdapter().parse(investment, account_kind=AccountKind.SAVINGS)

    card = ParsedFile(
        name="card.ofx",
        content=b"""<OFX><CCSTMTRS><CURDEF>CAD</CURDEF><ACCTID>1234</ACCTID>
<DTSTART>20260101</DTSTART><DTEND>20260131</DTEND>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260102</DTPOSTED>
<TRNAMT>-1</TRNAMT><FITID>1</FITID><NAME>X</NAME></STMTTRN>
<BALAMT>-1</BALAMT></CCSTMTRS></OFX>""",
    )
    with pytest.raises(AdapterError, match="asset account"):
        OfxAdapter().parse(card, account_kind=AccountKind.CHEQUING)


def test_ofx_requires_unique_fitid() -> None:
    transaction = """<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260102</DTPOSTED>
<TRNAMT>-1</TRNAMT><FITID>DUP</FITID><NAME>X</NAME></STMTTRN>"""
    content = (
        "<OFX><CCSTMTRS><CURDEF>CAD</CURDEF><ACCTID>1234</ACCTID>"
        "<DTSTART>20260101</DTSTART><DTEND>20260131</DTEND>"
        f"{transaction}{transaction}<BALAMT>-2</BALAMT></CCSTMTRS></OFX>"
    ).encode()

    with pytest.raises(AdapterError, match="duplicate FITID"):
        OfxAdapter().parse(
            ParsedFile(name="duplicate.ofx", content=content),
            account_kind=AccountKind.CREDIT_CARD,
        )


def test_fitid_is_authoritative_across_files_and_conflicts_fail_atomically() -> None:
    def statement(*, description: str, amount: str, closing: str) -> bytes:
        return f"""<OFX><CCSTMTRS><CURDEF>CAD</CURDEF><ACCTID>1234</ACCTID>
<DTSTART>20260101</DTSTART><DTEND>20260131</DTEND>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260102</DTPOSTED>
<TRNAMT>{amount}</TRNAMT><FITID>AUTHORITATIVE-1</FITID>
<NAME>{description}</NAME></STMTTRN>
<BALAMT>{closing}</BALAMT></CCSTMTRS></OFX>""".encode()

    objects = {
        "first.ofx": statement(description="Original Merchant", amount="-10", closing="-10"),
        "renamed.ofx": statement(description="Renamed Merchant", amount="-10", closing="-10"),
        "conflict.ofx": statement(description="Original Merchant", amount="-11", closing="-11"),
    }
    repository = InMemoryRepository(
        account_kinds={"card": AccountKind.CREDIT_CARD},
        account_currencies={"card": "CAD"},
    )
    pipeline = IngestionPipeline(store=MemoryObjectStore(objects), repository=repository)

    first = pipeline.process_file(account_id="card", file_key="first.ofx")
    renamed = pipeline.process_file(account_id="card", file_key="renamed.ofx")

    assert (first.added, renamed.added, renamed.skipped) == (1, 0, 1)
    assert len(repository.transactions) == 1
    assert next(iter(repository.transactions.values())).description_raw == "Original Merchant"

    with pytest.raises(ValueError, match="OFX FITID conflicts"):
        pipeline.process_file(account_id="card", file_key="conflict.ofx")

    assert len(repository.transactions) == 1
    assert "statement:card:conflict.ofx" not in repository.statements
