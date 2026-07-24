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
