from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from worker.adapters.base import AdapterError
from worker.adapters.im_bank_tz_pdf import ImBankTanzaniaPdfV1Adapter
from worker.models import AccountKind, Direction, ParsedFile
from worker.pipeline import AdapterRegistry, IngestionPipeline
from worker.reconcile import reconcile_statement
from worker.repository import InMemoryRepository
from worker.storage import MemoryObjectStore

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "im_bank_tz_pdf_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REAL_PDF = REPOSITORY_ROOT / "output" / "pdf" / "sanitized-adhoc-statement-2025-02-05.pdf"


def _fixture(name: str) -> str:
    return (FIXTURE_DIRECTORY / name).read_text(encoding="utf-8")


def _adapter(text: str) -> ImBankTanzaniaPdfV1Adapter:
    return ImBankTanzaniaPdfV1Adapter(ocr_reader=lambda _content, _limit: (text,))


def _file() -> ParsedFile:
    return ParsedFile(name="sanitized-im-bank-tz.pdf", content=b"%PDF fixture")


def test_detects_and_reconciles_the_versioned_tzs_layout() -> None:
    adapter = _adapter(_fixture("transactions-page.txt"))

    assert adapter.detect(_file()) == 0.99
    result = adapter.parse(_file(), account_kind=AccountKind.CHEQUING)
    reconciliation = reconcile_statement(result.statement, result.rows)

    assert result.adapter == "im_bank_tz_pdf_v1"
    assert result.statement.period_start == date(2025, 11, 4)
    assert result.statement.period_end == date(2025, 11, 30)
    assert result.statement.currency == "TZS"
    assert result.statement.account_ref_masked == "••••0001"
    assert result.statement.opening_balance == Decimal("941527.31")
    assert result.statement.closing_balance == Decimal("552860.04")
    assert len(result.rows) == 11
    assert sum(row.amount_native for row in result.rows) == Decimal("-388667.27")
    assert sum(row.direction is Direction.DEBIT for row in result.rows) == 10
    assert sum(row.direction is Direction.CREDIT for row in result.rows) == 1
    assert all(row.currency_native == "TZS" for row in result.rows)
    assert all(row.original_amount is None for row in result.rows)
    assert reconciliation.status == "ok"
    assert reconciliation.difference == Decimal("0.00")


def test_accepts_a_reconciling_zero_activity_statement() -> None:
    result = _adapter(_fixture("zero-activity-page.txt")).parse(
        _file(),
        account_kind=AccountKind.SAVINGS,
    )

    assert result.rows == ()
    assert reconcile_statement(result.statement, result.rows).status == "ok"
    assert result.statement.opening_balance == result.statement.closing_balance


def test_rejects_an_ocr_amount_that_conflicts_with_the_running_balance() -> None:
    corrupted = _fixture("transactions-page.txt").replace("80,430.31", "80,430.32", 1)

    with pytest.raises(AdapterError, match="running-balance delta"):
        _adapter(corrupted).parse(_file(), account_kind=AccountKind.CHEQUING)


def test_rejects_a_transaction_date_after_the_statement_period() -> None:
    corrupted = _fixture("transactions-page.txt").replace("29-11-25 29-11-25", "01-12-25 29-11-25")

    with pytest.raises(AdapterError, match="outside the statement period"):
        _adapter(corrupted).parse(_file(), account_kind=AccountKind.CHEQUING)


def test_rejects_import_into_a_credit_card_account() -> None:
    with pytest.raises(AdapterError, match="asset account"):
        _adapter(_fixture("transactions-page.txt")).parse(
            _file(),
            account_kind=AccountKind.CREDIT_CARD,
        )


def test_zero_activity_statement_persists_against_a_tzs_account() -> None:
    key = "statements/zero-activity.pdf"
    repository = InMemoryRepository(
        account_kinds={"tzs": AccountKind.CHEQUING},
        account_currencies={"tzs": "TZS"},
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: b"%PDF fixture"}),
        repository=repository,
        registry=AdapterRegistry(
            [_adapter(_fixture("zero-activity-page.txt"))],
            threshold=0.4,
        ),
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )

    first = pipeline.process_file(account_id="tzs", file_key=key)
    second = pipeline.process_file(account_id="tzs", file_key=key)

    assert (first.added, first.skipped, first.reconcile["status"]) == (0, 0, "ok")
    assert (second.added, second.skipped, second.reconcile["status"]) == (0, 0, "ok")
    assert len(repository.statements) == 1
    assert repository.account_refs["tzs"] == "••••0001"


@pytest.mark.skipif(
    not REAL_PDF.exists() or shutil.which("tesseract") is None,
    reason="user-supplied sanitized I&M TZS PDF and local Tesseract are optional",
)
def test_supplied_real_tzs_pdf_reconciles_and_reimports_idempotently() -> None:
    key = "statements/sanitized-im-bank-tz-v1.pdf"
    repository = InMemoryRepository(
        account_kinds={"tzs": AccountKind.CHEQUING},
        account_currencies={"tzs": "TZS"},
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: REAL_PDF.read_bytes()}),
        repository=repository,
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )

    first = pipeline.process_file(account_id="tzs", file_key=key)
    second = pipeline.process_file(account_id="tzs", file_key=key)

    assert first.adapter == "im_bank_tz_pdf_v1"
    assert (first.added, first.skipped, first.reconcile["status"]) == (17, 0, "ok")
    assert first.reconcile["reported_closing"] == "2994491.30"
    assert (second.added, second.skipped, second.reconcile["status"]) == (0, 17, "ok")
    assert len(repository.transactions) == 17
    assert all(row.amount_base is None for row in repository.transactions.values())
