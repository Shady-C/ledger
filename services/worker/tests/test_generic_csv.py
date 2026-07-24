from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from worker.adapters.base import AdapterError
from worker.adapters.generic_csv import GenericCsvAdapter
from worker.models import AccountKind, Direction, ParsedFile

FIXTURES = Path(__file__).parent / "fixtures"


def test_autolocates_header_and_normalizes_debit_credit_columns() -> None:
    content = (FIXTURES / "generic_card.csv").read_bytes()
    file = ParsedFile(name="generic_card.csv", content=content)
    adapter = GenericCsvAdapter()

    assert adapter.detect(file) == 0.88
    result = adapter.parse(file)

    assert result.statement.opening_balance == Decimal("100.00")
    assert result.statement.closing_balance == Decimal("110.00")
    assert [row.amount_native for row in result.rows] == [Decimal("25.00"), Decimal("-15.00")]
    assert [row.direction for row in result.rows] == [Direction.DEBIT, Direction.PAYMENT]


def test_parses_signed_amount_column_and_semicolon_delimiter() -> None:
    content = b"Date;Memo;Amount;Currency\n2026-03-01;Refund synthetic;-3.25;cad\n"
    result = GenericCsvAdapter().parse(ParsedFile(name="export.csv", content=content))

    assert result.rows[0].amount_native == Decimal("-3.25")
    assert result.rows[0].currency_native == "CAD"
    assert result.rows[0].direction is Direction.REFUND


@pytest.mark.parametrize(
    ("account_kind", "expected"),
    [
        (AccountKind.CREDIT_CARD, [Decimal("25.00"), Decimal("-15.00")]),
        (AccountKind.CHEQUING, [Decimal("-25.00"), Decimal("15.00")]),
        (AccountKind.SAVINGS, [Decimal("-25.00"), Decimal("15.00")]),
        (AccountKind.WALLET, [Decimal("-25.00"), Decimal("15.00")]),
    ],
)
def test_split_columns_apply_authoritative_account_kind_signs(
    account_kind: AccountKind, expected: list[Decimal]
) -> None:
    content = (FIXTURES / "generic_card.csv").read_bytes()
    result = GenericCsvAdapter().parse(
        ParsedFile(name="generic.csv", content=content),
        account_kind=account_kind,
    )

    assert [row.amount_native for row in result.rows] == expected


def test_signed_amount_format_fails_closed_for_asset_account() -> None:
    content = b"Date,Memo,Amount\n2026-03-01,Synthetic deposit,10.00\n"

    with pytest.raises(AdapterError, match="ambiguous for asset accounts"):
        GenericCsvAdapter().parse(
            ParsedFile(name="asset.csv", content=content),
            account_kind=AccountKind.CHEQUING,
        )


def test_slash_date_format_is_inferred_from_unambiguous_row() -> None:
    content = b"Date,Memo,Amount\n13/02/2026,Synthetic one,1.00\n03/04/2026,Synthetic two,2.00\n"

    result = GenericCsvAdapter().parse(ParsedFile(name="dates.csv", content=content))

    assert [row.booked_date.isoformat() for row in result.rows] == [
        "2026-02-13",
        "2026-04-03",
    ]


def test_unresolved_or_conflicting_slash_dates_fail_closed() -> None:
    ambiguous = b"Date,Memo,Amount\n01/02/2026,Synthetic,1.00\n"
    conflicting = (
        b"Date,Memo,Amount\n13/02/2026,Synthetic one,1.00\n03/14/2026,Synthetic two,2.00\n"
    )

    with pytest.raises(AdapterError, match="unresolved"):
        GenericCsvAdapter().parse(ParsedFile(name="ambiguous.csv", content=ambiguous))
    with pytest.raises(AdapterError, match="conflicting"):
        GenericCsvAdapter().parse(ParsedFile(name="conflicting.csv", content=conflicting))


def test_dmy_statement_period_uses_same_inferred_order_as_rows() -> None:
    content = (
        b"Statement Period,13/02/2026 to 28/02/2026\nDate,Memo,Amount\n14/02/2026,Synthetic,1.00\n"
    )

    result = GenericCsvAdapter().parse(ParsedFile(name="dmy-period.csv", content=content))

    assert result.statement.period_start.isoformat() == "2026-02-13"
    assert result.statement.period_end.isoformat() == "2026-02-28"
    assert result.rows[0].booked_date.isoformat() == "2026-02-14"


def test_ambiguous_statement_period_is_resolved_by_unambiguous_dmy_row() -> None:
    content = (
        b"Statement Period,01/02/2026 to 03/04/2026\nDate,Memo,Amount\n13/02/2026,Synthetic,1.00\n"
    )

    result = GenericCsvAdapter().parse(ParsedFile(name="resolved-period.csv", content=content))

    assert result.statement.period_start.isoformat() == "2026-02-01"
    assert result.statement.period_end.isoformat() == "2026-04-03"


def test_ambiguous_or_conflicting_statement_period_fails_closed() -> None:
    unresolved = (
        b"Statement Period,01/02/2026 to 03/04/2026\nDate,Memo,Amount\n2026-02-02,Synthetic,1.00\n"
    )
    conflicting = (
        b"Statement Period,13/02/2026 to 28/02/2026\nDate,Memo,Amount\n03/14/2026,Synthetic,1.00\n"
    )

    with pytest.raises(AdapterError, match="unresolved"):
        GenericCsvAdapter().parse(ParsedFile(name="unresolved-period.csv", content=unresolved))
    with pytest.raises(AdapterError, match="conflicting"):
        GenericCsvAdapter().parse(ParsedFile(name="conflicting-period.csv", content=conflicting))


@pytest.mark.parametrize(
    ("headers", "values", "field"),
    [
        (
            ["Date", "Transaction Date", "Memo", "Amount"],
            ["2026-01-01", "2026-01-01", "Synthetic", "1.00"],
            "booked date",
        ),
        (
            ["Date", "Description", "Memo", "Amount"],
            ["2026-01-01", "Synthetic", "Synthetic", "1.00"],
            "description",
        ),
        (
            ["Date", "Memo", "Amount", "Transaction Amount"],
            ["2026-01-01", "Synthetic", "1.00", "1.00"],
            "amount",
        ),
    ],
)
def test_multiple_alias_columns_fail_closed(
    headers: list[str], values: list[str], field: str
) -> None:
    with pytest.raises(AdapterError, match=rf"ambiguous {field} columns"):
        GenericCsvAdapter().parse_tabular_rows([headers, values])


def test_parses_original_currency_inline_fee_and_asset_flow_sign() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency,Original Amount,Original Currency,FX Fee\n"
        b"2026-01-03,Synthetic USD purchase,270000.00,,TZS,100.00,USD,5000.00\n"
    )

    result = GenericCsvAdapter().parse(
        ParsedFile(name="tzs.csv", content=content),
        account_kind=AccountKind.CHEQUING,
    )

    row = result.rows[0]
    assert row.amount_native == Decimal("-270000.00")
    assert row.currency_native == "TZS"
    assert row.original_amount == Decimal("-100.00")
    assert row.original_currency == "USD"
    assert row.fx_fee_amount_native == Decimal("5000.00")
    assert row.is_fx_fee is False


def test_asset_statement_recognizes_standalone_fx_fee_row() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency\n"
        b"2026-01-03,Foreign exchange fee,15.00,,USD\n"
    )

    row = GenericCsvAdapter().parse(
        ParsedFile(name="usd.csv", content=content),
        account_kind=AccountKind.CHEQUING,
    ).rows[0]

    assert row.amount_native == Decimal("-15.00")
    assert row.direction is Direction.FEE
    assert row.is_fx_fee is True
    assert row.fx_fee_amount_native is None


@pytest.mark.parametrize(
    "row",
    [
        b"2026-01-03,Synthetic,10.00,,TZS,5.00,\n",
        b"2026-01-03,Synthetic,10.00,,TZS,,USD\n",
    ],
)
def test_original_amount_and_currency_must_be_present_together(row: bytes) -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency,Original Amount,Original Currency\n"
        + row
    )

    with pytest.raises(AdapterError, match="must both be present"):
        GenericCsvAdapter().parse(
            ParsedFile(name="malformed.csv", content=content),
            account_kind=AccountKind.CHEQUING,
        )


def test_mixed_posted_currencies_require_separate_accounts() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency\n"
        b"2026-01-03,Synthetic TZS,100.00,,TZS\n"
        b"2026-01-04,Synthetic USD,1.00,,USD\n"
    )

    with pytest.raises(AdapterError, match="mixes multiple native currencies"):
        GenericCsvAdapter().parse(
            ParsedFile(name="mixed.csv", content=content),
            account_kind=AccountKind.CHEQUING,
        )


def test_explicit_standalone_fx_fee_flag_is_authoritative() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency,Is FX Fee\n"
        b"2026-01-03,Synthetic bank charge,15.00,,USD,yes\n"
    )

    row = GenericCsvAdapter().parse(
        ParsedFile(name="explicit-fee.csv", content=content),
        account_kind=AccountKind.CHEQUING,
    ).rows[0]

    assert row.is_fx_fee is True
    assert row.direction is Direction.FEE
    assert row.fx_fee_amount_native is None


def test_standalone_fx_fee_with_matching_fee_column_is_not_treated_as_inline() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency,FX Fee\n"
        b"2026-01-03,Foreign exchange fee,15.00,,USD,15.00\n"
    )

    row = GenericCsvAdapter().parse(
        ParsedFile(name="fee-column.csv", content=content),
        account_kind=AccountKind.CHEQUING,
    ).rows[0]

    assert row.is_fx_fee is True
    assert row.fx_fee_amount_native is None


def test_general_bank_commission_is_not_misreported_as_fx() -> None:
    content = (
        b"Date,Description,Debit,Credit,Currency\n"
        b"2026-01-03,General bank commission,15.00,,USD\n"
    )

    row = GenericCsvAdapter().parse(
        ParsedFile(name="commission.csv", content=content),
        account_kind=AccountKind.CHEQUING,
    ).rows[0]

    assert row.is_fx_fee is False


def test_explicit_balance_currency_cannot_be_overwritten_by_row_currency() -> None:
    content = (
        b"Currency,TZS\n"
        b"Opening Balance,1000.00 TZS\n"
        b"Date,Description,Debit,Credit,Currency\n"
        b"2026-01-03,Synthetic,10.00,,USD\n"
    )

    with pytest.raises(AdapterError, match="balance currency differs"):
        GenericCsvAdapter().parse(
            ParsedFile(name="wrong-balance-currency.csv", content=content),
            account_kind=AccountKind.CHEQUING,
        )


def test_usd_posted_tzs_original_refund_keeps_matching_flow_sign() -> None:
    content = (
        b"Date,Description,Amount,Currency,Original Amount,Original Currency\n"
        b"2026-01-03,Foreign purchase refund,-10.00,USD,25000.00,TZS\n"
    )

    row = GenericCsvAdapter().parse(
        ParsedFile(name="refund.csv", content=content),
        account_kind=AccountKind.CREDIT_CARD,
    ).rows[0]

    assert row.amount_native == Decimal("-10.00")
    assert row.original_amount == Decimal("-25000.00")
    assert row.original_currency == "TZS"
    assert row.direction is Direction.REFUND
