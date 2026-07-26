from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from worker.adapters.base import AdapterError
from worker.adapters.im_bank_tz_pdf import ImBankTanzaniaPdfV1Adapter
from worker.adapters.wealthsimple_chequing_pdf import (
    WealthsimpleChequingPdfV1Adapter,
    _PositionedWord,
)
from worker.models import AccountKind, Direction, ParsedFile
from worker.pipeline import AdapterRegistry, IngestionPipeline
from worker.reconcile import reconcile_statement
from worker.repository import InMemoryRepository
from worker.storage import MemoryObjectStore

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "wealthsimple_chequing_pdf_v1"
Pages = tuple[tuple[_PositionedWord, ...], ...]


def _fixture_pages() -> Pages:
    pages: dict[int, list[_PositionedWord]] = {}
    fixture = FIXTURE_DIRECTORY / "two-page-positioned.txt"
    for raw_line in fixture.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        page, top, x0, x1, text = raw_line.split("|", 4)
        pages.setdefault(int(page), []).append(
            _PositionedWord(
                text=text,
                top=float(top),
                x0=float(x0),
                x1=float(x1),
            )
        )
    return tuple(tuple(pages[index]) for index in sorted(pages))


def _adapter(pages: Pages | None = None) -> WealthsimpleChequingPdfV1Adapter:
    positioned_pages = pages or _fixture_pages()
    return WealthsimpleChequingPdfV1Adapter(
        word_reader=lambda _content, limit: (
            positioned_pages if limit is None else positioned_pages[:limit]
        )
    )


def _file() -> ParsedFile:
    return ParsedFile(name="sanitized-wealthsimple.pdf", content=b"%PDF synthetic")


def _replace_word(
    pages: Pages,
    *,
    page: int,
    top: float,
    old: str,
    new: str,
) -> Pages:
    changed = False
    result: list[tuple[_PositionedWord, ...]] = []
    for page_index, words in enumerate(pages, 1):
        updated: list[_PositionedWord] = []
        for word in words:
            if page_index == page and word.top == top and word.text == old:
                updated.append(replace(word, text=new))
                changed = True
            else:
                updated.append(word)
        result.append(tuple(updated))
    assert changed, (page, top, old)
    return tuple(result)


def _without_tops(pages: Pages, *, page: int, tops: set[float]) -> Pages:
    return tuple(
        tuple(
            word
            for word in words
            if page_index != page or word.top not in tops
        )
        for page_index, words in enumerate(pages, 1)
    )


def test_detects_parses_and_reconciles_the_versioned_cad_layout() -> None:
    adapter = _adapter()

    assert adapter.detect(_file()) == 0.99
    result = adapter.parse(_file(), account_kind=AccountKind.SAVINGS)
    reconciliation = reconcile_statement(result.statement, result.rows)

    assert result.adapter == "wealthsimple_chequing_pdf_v1"
    assert result.statement.period_start == date(2026, 2, 1)
    assert result.statement.period_end == date(2026, 2, 28)
    assert result.statement.opening_balance == Decimal("1000.00")
    assert result.statement.closing_balance == Decimal("1300.00")
    assert result.statement.currency == "CAD"
    assert result.statement.account_ref_masked == "••••3000"
    assert len(result.rows) == 5
    assert result.rows[2].posted_date == date(2026, 2, 11)
    assert result.rows[2].description_raw == (
        "Synthetic travel purchase with wrapped location details"
    )
    assert [row.direction for row in result.rows] == [
        Direction.CREDIT,
        Direction.DEBIT,
        Direction.DEBIT,
        Direction.INTEREST,
        Direction.FEE,
    ]
    assert all(row.currency_native == "CAD" for row in result.rows)
    assert reconciliation.status == "ok"
    assert reconciliation.difference == Decimal("0.00")


def test_real_pdfplumber_reader_parses_the_sanitized_two_page_pdf() -> None:
    fixture = FIXTURE_DIRECTORY / "two-page-positioned.pdf"
    file = ParsedFile(name=fixture.name, content=fixture.read_bytes())
    adapter = WealthsimpleChequingPdfV1Adapter()

    assert adapter.detect(file) == 0.99
    result = adapter.parse(file, account_kind=AccountKind.CHEQUING)

    assert len(result.rows) == 5
    assert result.statement.account_ref_masked == "••••3000"
    assert result.statement.closing_balance == Decimal("1300.00")
    assert reconcile_statement(result.statement, result.rows).status == "ok"


def test_registry_does_not_run_the_later_ocr_detector_after_an_exact_match() -> None:
    def unexpected_ocr(_content: bytes, _limit: int | None) -> tuple[str, ...]:
        pytest.fail("Wealthsimple selection must not invoke OCR")

    registry = AdapterRegistry(
        [_adapter(), ImBankTanzaniaPdfV1Adapter(ocr_reader=unexpected_ocr)]
    )

    assert registry.select(_file()).name == "wealthsimple_chequing_pdf_v1"


def test_changed_institution_fingerprint_is_not_claimed() -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=38.0,
        old="Wealthsimple",
        new="Unknown institution",
    )
    adapter = _adapter(pages)

    assert adapter.detect(_file()) == 0.0
    with pytest.raises(AdapterError, match="fingerprint"):
        adapter.parse(_file(), account_kind=AccountKind.CHEQUING)


def test_rejects_a_malformed_statement_period() -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=48.0,
        old="Feb 1 - Feb 28, 2026",
        new="Feb 1 through Feb 28, 2026",
    )

    with pytest.raises(AdapterError, match="one statement period"):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_import_into_a_card_account() -> None:
    with pytest.raises(AdapterError, match="asset account"):
        _adapter().parse(_file(), account_kind=AccountKind.CREDIT_CARD)


@pytest.mark.parametrize(
    ("top", "old", "new", "message"),
    [
        (305.0, "2026-02-02", "2026-01-31", "booking date.*outside"),
        (355.0, "2026-02-11", "2026-03-01", "posted date.*outside"),
    ],
)
def test_rejects_transaction_dates_outside_the_statement_period(
    top: float,
    old: str,
    new: str,
    message: str,
) -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=top,
        old=old,
        new=new,
    )

    with pytest.raises(AdapterError, match=message):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_a_missing_transaction_row_via_running_balance() -> None:
    pages = _without_tops(_fixture_pages(), page=1, tops={330.0})

    with pytest.raises(AdapterError, match="running-balance delta"):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_a_whole_missing_page_even_when_its_transactions_net_to_zero() -> None:
    pages = _fixture_pages()

    with pytest.raises(AdapterError, match="page numbering"):
        _adapter((pages[0],)).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_an_incorrect_running_balance() -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=330.0,
        old="$1,374.75",
        new="$1,374.74",
    )

    with pytest.raises(AdapterError, match="running-balance delta"):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_an_incorrect_printed_closing_summary() -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=203.0,
        old="$1,300.00",
        new="$1,301.00",
    )

    with pytest.raises(AdapterError, match="printed closing balance"):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_rejects_duplicate_or_changed_activity_headers() -> None:
    pages = _fixture_pages()
    duplicate = _PositionedWord(
        text="DATE POSTED DATE DESCRIPTION AMOUNT (CAD) BALANCE (CAD)",
        top=290.0,
        x0=24.0,
        x1=434.0,
    )
    duplicated = ((duplicate, *pages[0]), pages[1])

    with pytest.raises(AdapterError, match="one unambiguous activity header"):
        _adapter(duplicated).parse(_file(), account_kind=AccountKind.SAVINGS)

    changed = _replace_word(
        pages,
        page=2,
        top=30.0,
        old="DATE POSTED DATE DESCRIPTION AMOUNT (CAD) BALANCE (CAD)",
        new="DATE POSTED DATE DESCRIPTION AMOUNT (CAD) AVAILABLE BALANCE (CAD)",
    )
    with pytest.raises(AdapterError, match="one unambiguous activity header"):
        _adapter(changed).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_accepts_only_a_provably_safe_zero_activity_statement() -> None:
    pages = _fixture_pages()
    pages = _without_tops(pages, page=1, tops={305.0, 330.0, 355.0, 365.5})
    pages = _without_tops(pages, page=2, tops={55.0, 80.0})
    pages = _replace_word(
        pages,
        page=1,
        top=203.0,
        old="$1,300.00",
        new="$1,000.00",
    )

    result = _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)

    assert result.rows == ()
    assert result.statement.opening_balance == result.statement.closing_balance
    assert reconcile_statement(result.statement, result.rows).status == "ok"


def test_merchant_name_containing_charge_is_not_misclassified_as_a_fee() -> None:
    pages = _replace_word(
        _fixture_pages(),
        page=1,
        top=330.0,
        old="Synthetic market purchase",
        new="ChargePoint Canada",
    )

    result = _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)

    assert result.rows[1].direction == Direction.DEBIT


def test_zero_activity_rejects_unparsed_transaction_like_content() -> None:
    pages = _fixture_pages()
    pages = _without_tops(pages, page=1, tops={305.0, 330.0, 355.0, 365.5})
    pages = _without_tops(pages, page=2, tops={55.0, 80.0})
    pages = _replace_word(
        pages,
        page=1,
        top=203.0,
        old="$1,300.00",
        new="$1,000.00",
    )
    malformed = _PositionedWord(
        text="2026-02-14",
        top=305.0,
        x0=24.0,
        x1=63.0,
    )
    pages = ((*pages[0], malformed), pages[1])

    with pytest.raises(AdapterError, match="posted date"):
        _adapter(pages).parse(_file(), account_kind=AccountKind.SAVINGS)


def test_pipeline_persists_once_and_rejects_a_non_cad_account() -> None:
    key = "statements/sanitized-wealthsimple.pdf"
    repository = InMemoryRepository(
        account_kinds={"cad": AccountKind.SAVINGS},
        account_currencies={"cad": "CAD"},
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: b"%PDF synthetic"}),
        repository=repository,
        registry=AdapterRegistry([_adapter()]),
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )

    first = pipeline.process_file(account_id="cad", file_key=key)
    second = pipeline.process_file(account_id="cad", file_key=key)

    assert first.adapter == "wealthsimple_chequing_pdf_v1"
    assert (first.added, first.skipped, first.reconcile["status"]) == (5, 0, "ok")
    assert (second.added, second.skipped, second.reconcile["status"]) == (0, 5, "ok")
    assert len(repository.transactions) == 5
    assert len(repository.statements) == 1
    assert repository.account_refs["cad"] == "••••3000"

    non_cad_repository = InMemoryRepository(
        account_kinds={"usd": AccountKind.SAVINGS},
        account_currencies={"usd": "USD"},
    )
    non_cad_pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: b"%PDF synthetic"}),
        repository=non_cad_repository,
        registry=AdapterRegistry([_adapter()]),
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )
    with pytest.raises(AdapterError, match="currency does not match"):
        non_cad_pipeline.process_file(account_id="usd", file_key=key)
    assert non_cad_repository.transactions == {}
    assert non_cad_repository.statements == {}


def test_pipeline_rejects_a_conflicting_account_reference() -> None:
    key = "statements/sanitized-wealthsimple.pdf"
    repository = InMemoryRepository(
        account_kinds={"cad": AccountKind.SAVINGS},
        account_currencies={"cad": "CAD"},
        account_refs={"cad": "••••9999"},
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: b"%PDF synthetic"}),
        repository=repository,
        registry=AdapterRegistry([_adapter()]),
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )

    with pytest.raises(ValueError, match="does not match selected account"):
        pipeline.process_file(account_id="cad", file_key=key)

    assert repository.transactions == {}
    assert repository.statements == {}
