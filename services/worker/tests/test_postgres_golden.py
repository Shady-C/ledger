from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from worker.pipeline import IngestionPipeline
from worker.repository import PostgresRepository
from worker.storage import MemoryObjectStore

DATABASE_URL = os.getenv("LEDGER_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="set LEDGER_TEST_DATABASE_URL to run PostgreSQL persistence tests",
    ),
]


def test_postgres_persists_golden_close_at_2855_59(amex_workbook_bytes) -> None:
    assert DATABASE_URL is not None
    unique = uuid4().hex
    objects = {
        f"postgres/{unique}-01.xlsx": amex_workbook_bytes(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening=Decimal("1000.00"),
            closing=Decimal("1200.00"),
            transactions=[
                (date(2026, 1, 3), "Synthetic One", Decimal("500.00"), None, f"{unique}-1"),
                (date(2026, 1, 20), "Payment", Decimal("-300.00"), None, f"{unique}-2"),
            ],
        ),
        f"postgres/{unique}-02.xlsx": amex_workbook_bytes(
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            opening=Decimal("1200.00"),
            closing=Decimal("1700.25"),
            transactions=[
                (date(2026, 2, 3), "Synthetic Two", Decimal("750.50"), None, f"{unique}-3"),
                (date(2026, 2, 20), "Refund", Decimal("-250.25"), None, f"{unique}-4"),
            ],
        ),
        f"postgres/{unique}-03.xlsx": amex_workbook_bytes(
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening=Decimal("1700.25"),
            closing=Decimal("2855.59"),
            transactions=[
                (date(2026, 3, 3), "Synthetic Three", Decimal("1355.34"), None, f"{unique}-5"),
                (date(2026, 3, 20), "Autopay", Decimal("-200.00"), None, f"{unique}-6"),
            ],
        ),
    }
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO institution (name) VALUES (%s) RETURNING id::text",
            (f"Worker Test {unique}",),
        )
        institution_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO account (
                institution_id, display_name, kind, native_currency, market_code
            )
            VALUES (%s, %s, 'credit_card', 'CAD', 'CA')
            RETURNING id::text
            """,
            (institution_id, f"Worker Test {unique}"),
        )
        account_id = cursor.fetchone()[0]

    repository = PostgresRepository(DATABASE_URL)
    pipeline = IngestionPipeline(store=MemoryObjectStore(objects), repository=repository)
    try:
        results = [
            pipeline.process_file(account_id=account_id, file_key=file_key) for file_key in objects
        ]
        with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT closing_balance, reconcile_status
                FROM statement
                WHERE account_id = %s
                ORDER BY period_end
                """,
                (account_id,),
            )
            persisted = cursor.fetchall()
            cursor.execute("SELECT count(*) FROM txn WHERE account_id = %s", (account_id,))
            transaction_count = cursor.fetchone()[0]

        assert [result.reconcile["status"] for result in results if result.reconcile] == [
            "ok",
            "ok",
            "ok",
        ]
        assert persisted[-1][0] == Decimal("2855.59")
        assert [row[1] for row in persisted] == ["ok", "ok", "ok"]
        assert transaction_count == 6
    finally:
        with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM txn WHERE account_id = %s", (account_id,))
            cursor.execute("DELETE FROM statement WHERE account_id = %s", (account_id,))
            cursor.execute("DELETE FROM account WHERE id = %s", (account_id,))
            cursor.execute("DELETE FROM institution WHERE id = %s", (institution_id,))
