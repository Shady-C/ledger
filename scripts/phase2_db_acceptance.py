"""Exercise Phase 2 migrations in safety-prefixed disposable databases.

Prerequisite: a PostgreSQL 16 + pgvector server matching the development
stack. The default administrative URL targets the local Docker Compose
PostgreSQL service. Run with:

    uv run --project services/worker --extra dev \
      python scripts/phase2_db_acceptance.py

The script builds two uniquely named ``ledger_phase2_acceptance_*`` databases:
one for a CAD Phase 1 upgrade/rollback cycle and one for a non-CAD migration
whose CAD valuation must remain pending. Both databases are dropped in a
``finally`` block, including when an assertion fails.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from worker.repository import PostgresRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = "postgresql://ledger:ledger_dev_password@localhost:5432/postgres"
DATABASE_PREFIX = "ledger_phase2_acceptance_"
DATABASE_NAME_PATTERN = re.compile(
    rf"^{re.escape(DATABASE_PREFIX)}(?:cad|pending)_[0-9a-f]{{20}}$"
)

MIGRATION_NAMES = (
    "202607240001_enable_extensions.sql",
    "202607240002_create_reference_data.sql",
    "202607240003_create_ledger.sql",
    "202607240004_create_ingestion.sql",
    "202607240005_add_ingestion_safety.sql",
    "202607240006_add_phase1_foundations.sql",
    "202607240007_enqueue_phase1_categorization_backfill.sql",
    "202607240008_correct_fallback_category_confidence.sql",
    "202607240009_enforce_ofx_fitid_identity.sql",
    "202607240010_guard_referenced_category_kind.sql",
    "202607240011_tighten_masked_account_references.sql",
    "202607240012_add_phase2_multicurrency.sql",
    "202607240013_add_phase2_analytics.sql",
)
PHASE1_MIGRATION_COUNT = 11


@dataclass(frozen=True, slots=True)
class Migration:
    name: str
    up_sql: str
    down_sql: str


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    migration_count: int
    disposable_database_count: int
    cad_backfill_preserved: bool
    rollback_reapply_succeeded: bool
    currency_guard_sqlstates: tuple[str, ...]
    pending_native_preserved: bool
    queued_job_kinds: tuple[str, ...]
    analytics_mode_promotion_succeeded: bool


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-url",
        default=os.getenv("LEDGER_PHASE2_ACCEPTANCE_ADMIN_URL", DEFAULT_ADMIN_URL),
        help="administrative PostgreSQL URL used only for disposable acceptance databases",
    )
    return parser.parse_args(arguments)


def load_migrations() -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    migration_directory = REPOSITORY_ROOT / "db" / "migrations"
    for name in MIGRATION_NAMES:
        path = migration_directory / name
        if not path.is_file():
            raise RuntimeError(f"required migration is missing: {name}")
        content = path.read_text()
        before_down, down_marker, down_sql = content.partition("-- migrate:down")
        up_marker, up_separator, up_sql = before_down.partition("-- migrate:up")
        if up_marker.strip() or not up_separator or not down_marker:
            raise RuntimeError(f"migration markers are malformed: {name}")
        migrations.append(Migration(name, up_sql.strip(), down_sql.strip()))
    return tuple(migrations)


def _validate_database_name(database_name: str) -> None:
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise ValueError(
            "refusing disposable database operation outside the Phase 2 acceptance prefix"
        )


def disposable_database_url(admin_url: str, database_name: str) -> str:
    _validate_database_name(database_name)
    return make_conninfo(admin_url, dbname=database_name)


def create_database(admin_url: str, database_name: str) -> None:
    _validate_database_name(database_name)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        existing = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
        ).fetchone()
        if existing is not None:
            raise RuntimeError(f"refusing to reuse existing database {database_name}")
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )


def drop_database(admin_url: str, database_name: str) -> None:
    _validate_database_name(database_name)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
        )


def apply_migrations(database_url: str, migrations: Sequence[Migration]) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        for migration in migrations:
            with connection.transaction():
                connection.execute(migration.up_sql)


def rollback_migrations(database_url: str, migrations: Sequence[Migration]) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        for migration in migrations:
            with connection.transaction():
                connection.execute(migration.down_sql)


def seed_legacy_cad(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO account (id, display_name, kind, native_currency)
            VALUES (
                '10000000-0000-4000-8000-000000000001',
                'Legacy CAD card',
                'credit_card',
                'CAD'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO statement (
                id, account_id, period_start, period_end,
                opening_balance, closing_balance,
                currency, source_file_key, reconcile_status
            ) VALUES (
                '20000000-0000-4000-8000-000000000001',
                '10000000-0000-4000-8000-000000000001',
                DATE '2026-01-01', DATE '2026-01-31',
                1000.00, 1123.45,
                'CAD', 'acceptance/legacy-cad.csv', 'ok'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO txn (
                id, account_id, statement_id, booked_date, posted_date,
                description_raw, amount_native, currency_native,
                amount_base, currency_base, fx_rate, fx_rate_date,
                dedup_hash, direction, enrichment
            ) VALUES (
                '30000000-0000-4000-8000-000000000001',
                '10000000-0000-4000-8000-000000000001',
                '20000000-0000-4000-8000-000000000001',
                DATE '2026-01-02', DATE '2026-01-03',
                'Legacy USD purchase',
                123.45, 'CAD', 123.45, 'CAD', 1, DATE '2026-01-02',
                'acceptance-legacy-cad-foreign', 'debit',
                '{"foreign_spend":{"amount":"100.00","currency":"USD"},'
                '"fx_source":"identity"}'::jsonb
            )
            """
        )


def seed_legacy_pending(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE ledger_settings SET base_currency = 'USD' WHERE singleton"
        )
        connection.execute(
            """
            INSERT INTO account (id, display_name, kind, native_currency)
            VALUES (
                '12000000-0000-4000-8000-000000000001',
                'Legacy TZS account',
                'chequing',
                'TZS'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO statement (
                id, account_id, period_start, period_end,
                opening_balance, closing_balance,
                currency, source_file_key, reconcile_status
            ) VALUES (
                '22000000-0000-4000-8000-000000000001',
                '12000000-0000-4000-8000-000000000001',
                DATE '2026-03-01', DATE '2026-03-31',
                1000000.00, 900000.00,
                'TZS', 'acceptance/legacy-tzs.csv', 'ok'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO txn (
                id, account_id, statement_id, booked_date, posted_date,
                description_raw, amount_native, currency_native,
                amount_base, currency_base, fx_rate, fx_rate_date,
                dedup_hash, direction, enrichment
            ) VALUES (
                '32000000-0000-4000-8000-000000000001',
                '12000000-0000-4000-8000-000000000001',
                '22000000-0000-4000-8000-000000000001',
                DATE '2026-03-02', DATE '2026-03-03',
                'Legacy USD purchase posted in TZS',
                -100000.00, 'TZS', -40.00, 'USD', 0.00040000, DATE '2026-03-02',
                'acceptance-legacy-tzs-pending', 'debit',
                '{"foreign_spend":{"amount":"40.00","currency":"USD"},'
                '"fx_source":"legacy-usd"}'::jsonb
            )
            """
        )


def _expect_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, found {actual!r}")


def assert_cad_backfill(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT amount_native, currency_native, amount_base, currency_base,
                   fx_rate, fx_rate_date, original_amount, original_currency,
                   enrichment
            FROM txn
            WHERE id = '30000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
    if row is None:
        raise AssertionError("legacy CAD transaction disappeared during migration")
    expected = (
        Decimal("123.45"),
        "CAD",
        Decimal("123.45"),
        "CAD",
        Decimal("1.00000000"),
        date(2026, 1, 2),
        Decimal("100.00"),
        "USD",
    )
    _expect_equal(row[:8], expected, "legacy CAD monetary layers")
    enrichment = row[8]
    if not isinstance(enrichment, dict):
        raise TypeError("legacy CAD enrichment was not returned as an object")
    if "foreign_spend" in enrichment:
        raise AssertionError("foreign_spend remained after first-class backfill")
    _expect_equal(enrichment.get("fx_source"), "identity", "legacy CAD FX source")


def assert_phase1_rollback(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT amount_native, currency_native, amount_base, currency_base,
                   fx_rate, fx_rate_date, enrichment
            FROM txn
            WHERE id = '30000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        analytics_table = connection.execute(
            "SELECT to_regclass('public.analytics_run')"
        ).fetchone()
    if row is None:
        raise AssertionError("legacy CAD transaction disappeared during rollback")
    _expect_equal(
        row[:6],
        (
            Decimal("123.45"),
            "CAD",
            Decimal("123.45"),
            "CAD",
            Decimal("1.00000000"),
            date(2026, 1, 2),
        ),
        "rolled-back CAD monetary values",
    )
    enrichment = row[6]
    if not isinstance(enrichment, dict):
        raise TypeError("rolled-back enrichment was not returned as an object")
    _expect_equal(
        enrichment.get("foreign_spend"),
        {"amount": "100.00", "currency": "USD"},
        "rolled-back foreign_spend evidence",
    )
    _expect_equal(analytics_table, (None,), "analytics schema after Phase 2 rollback")


def assert_pending_upgrade(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT amount_native, currency_native, amount_base, currency_base,
                   fx_rate, fx_rate_date, original_amount, original_currency,
                   enrichment
            FROM txn
            WHERE id = '32000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        settings = connection.execute(
            "SELECT base_currency FROM ledger_settings WHERE singleton"
        ).fetchone()
        statement = connection.execute(
            """
            SELECT opening_balance, closing_balance, currency, reconcile_status
            FROM statement
            WHERE id = '22000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
    if row is None:
        raise AssertionError("legacy TZS transaction disappeared during migration")
    _expect_equal(
        row[:8],
        (
            Decimal("-100000.00"),
            "TZS",
            None,
            "CAD",
            None,
            None,
            Decimal("-40.00"),
            "USD",
        ),
        "pending TZS monetary layers",
    )
    enrichment = row[8]
    if not isinstance(enrichment, dict):
        raise TypeError("pending TZS enrichment was not returned as an object")
    _expect_equal(enrichment, {}, "pending TZS enrichment")
    _expect_equal(settings, ("CAD",), "fixed reporting currency")
    _expect_equal(
        statement,
        (Decimal("1000000.00"), Decimal("900000.00"), "TZS", "ok"),
        "native statement truth",
    )


def assert_phase2_jobs(database_url: str) -> tuple[str, ...]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT kind, payload, status, deduplication_key
            FROM job
            WHERE kind IN ('fx_refresh', 'analytics_refresh')
            ORDER BY kind, created_at, id
            """
        ).fetchall()
    expected = {
        "analytics_refresh": ({"mode": "full"}, "analytics-refresh:ledger"),
        "fx_refresh": (
            {"target_base_currency": "CAD"},
            "phase2:fx-refresh:CAD:backfill:v1",
        ),
    }
    _expect_equal(len(rows), len(expected), "queued Phase 2 job count")
    by_kind: dict[str, tuple[object, object, object]] = {}
    for kind, payload, status, deduplication_key in rows:
        by_kind[str(kind)] = (payload, status, deduplication_key)
    _expect_equal(set(by_kind), set(expected), "queued Phase 2 job kinds")
    for kind, (payload, deduplication_key) in expected.items():
        actual_payload, status, actual_key = by_kind[kind]
        _expect_equal(actual_payload, payload, f"{kind} payload")
        _expect_equal(status, "queued", f"{kind} status")
        _expect_equal(actual_key, deduplication_key, f"{kind} deduplication key")
    return tuple(sorted(by_kind))


def _assert_check_violation(
    connection: psycopg.Connection[tuple[Any, ...]],
    statement: str,
    label: str,
) -> str:
    try:
        connection.execute(statement)
    except psycopg.errors.CheckViolation as error:
        _expect_equal(error.sqlstate, "23514", f"{label} SQLSTATE")
        return "23514"
    raise AssertionError(f"{label} was unexpectedly accepted")


def assert_currency_guards_and_pending_insert(database_url: str) -> tuple[str, ...]:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO account (id, display_name, kind, native_currency)
            VALUES
              ('11000000-0000-4000-8000-000000000001', 'TZS account', 'chequing', 'TZS'),
              ('11000000-0000-4000-8000-000000000002', 'USD account', 'chequing', 'USD');

            INSERT INTO statement (
                id, account_id, period_start, period_end,
                opening_balance, closing_balance,
                currency, source_file_key, reconcile_status
            ) VALUES
              (
                '21000000-0000-4000-8000-000000000001',
                '11000000-0000-4000-8000-000000000001',
                DATE '2026-02-01', DATE '2026-02-28',
                1000000.00, 900000.00,
                'TZS', 'acceptance/tzs.csv', 'ok'
              ),
              (
                '21000000-0000-4000-8000-000000000002',
                '11000000-0000-4000-8000-000000000002',
                DATE '2026-02-01', DATE '2026-02-28',
                1000.00, 900.00,
                'USD', 'acceptance/usd.csv', 'ok'
              );

            INSERT INTO txn (
                id, account_id, statement_id, booked_date, description_raw,
                amount_native, currency_native,
                amount_base, currency_base, fx_rate, fx_rate_date,
                dedup_hash, direction
            ) VALUES (
                '31000000-0000-4000-8000-000000000001',
                '11000000-0000-4000-8000-000000000001',
                '21000000-0000-4000-8000-000000000001',
                DATE '2026-02-03', 'Pending TZS valuation',
                -100000.00, 'TZS', NULL, 'CAD', NULL, NULL,
                'acceptance-pending-tzs', 'debit'
            )
            """
        )

    with psycopg.connect(database_url, autocommit=True) as connection:
        sqlstates = (
            _assert_check_violation(
                connection,
                """
                INSERT INTO statement (
                    id, account_id, period_start, period_end, currency, source_file_key
                ) VALUES (
                    '21000000-0000-4000-8000-000000000003',
                    '11000000-0000-4000-8000-000000000001',
                    DATE '2026-03-01', DATE '2026-03-31',
                    'USD', 'acceptance/invalid-statement.csv'
                )
                """,
                "mixed statement currency",
            ),
            _assert_check_violation(
                connection,
                """
                INSERT INTO txn (
                    id, account_id, booked_date, description_raw,
                    amount_native, currency_native,
                    amount_base, currency_base, fx_rate, fx_rate_date,
                    dedup_hash, direction
                ) VALUES (
                    '31000000-0000-4000-8000-000000000002',
                    '11000000-0000-4000-8000-000000000001',
                    DATE '2026-02-04', 'Wrong posted currency',
                    -40.00, 'USD', NULL, 'CAD', NULL, NULL,
                    'acceptance-wrong-posted-currency', 'debit'
                )
                """,
                "mixed transaction currency",
            ),
            _assert_check_violation(
                connection,
                """
                INSERT INTO txn (
                    id, account_id, statement_id, booked_date, description_raw,
                    amount_native, currency_native,
                    amount_base, currency_base, fx_rate, fx_rate_date,
                    dedup_hash, direction
                ) VALUES (
                    '31000000-0000-4000-8000-000000000003',
                    '11000000-0000-4000-8000-000000000001',
                    '21000000-0000-4000-8000-000000000002',
                    DATE '2026-02-04', 'Wrong statement account',
                    -40000.00, 'TZS', NULL, 'CAD', NULL, NULL,
                    'acceptance-wrong-statement-account', 'debit'
                )
                """,
                "transaction/statement mismatch",
            ),
        )
        pending = connection.execute(
            """
            SELECT amount_native, currency_native, amount_base,
                   currency_base, fx_rate, fx_rate_date
            FROM txn
            WHERE id = '31000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        invalid_statement_count = connection.execute(
            """
            SELECT count(*) FROM statement
            WHERE id = '21000000-0000-4000-8000-000000000003'
            """
        ).fetchone()
        invalid_transaction_count = connection.execute(
            """
            SELECT count(*) FROM txn
            WHERE id IN (
                '31000000-0000-4000-8000-000000000002',
                '31000000-0000-4000-8000-000000000003'
            )
            """
        ).fetchone()
    _expect_equal(
        pending,
        (Decimal("-100000.00"), "TZS", None, "CAD", None, None),
        "valid pending TZS insert",
    )
    _expect_equal(invalid_statement_count, (0,), "rejected statement persistence")
    _expect_equal(invalid_transaction_count, (0,), "rejected transaction persistence")
    return sqlstates


def assert_analytics_mode_promotion(database_url: str) -> None:
    """Exercise queued and in-flight mode promotion against PostgreSQL."""

    repository = PostgresRepository(database_url)
    with psycopg.connect(database_url) as connection:
        connection.execute("DELETE FROM job")
        queued_id = connection.execute(
            """
            INSERT INTO job (kind, payload, deduplication_key)
            VALUES (
                'analytics_refresh',
                '{"mode":"incremental"}'::jsonb,
                'analytics-refresh:ledger'
            )
            RETURNING id::text
            """
        ).fetchone()
    if queued_id is None:
        raise AssertionError("could not seed queued incremental analytics refresh")

    repository.enqueue_analytics_refresh_job(mode="full")
    with psycopg.connect(database_url) as connection:
        promoted_queued = connection.execute(
            """
            SELECT status, payload
            FROM job
            WHERE id = %s
            """,
            (queued_id[0],),
        ).fetchone()
    _expect_equal(
        promoted_queued,
        ("queued", {"mode": "full", "rerun_requested": True}),
        "queued analytics mode promotion",
    )
    first_full = repository.claim_next_job(timeout_seconds=60)
    if first_full is None:
        raise AssertionError("promoted queued analytics refresh could not be claimed")
    _expect_equal(first_full.payload, {"mode": "full"}, "claimed queued promotion")
    repository.complete_job(first_full, {"accepted": True}, needs_ai=False)

    with psycopg.connect(database_url) as connection:
        connection.execute("DELETE FROM job")
        connection.execute(
            """
            INSERT INTO job (kind, payload, deduplication_key)
            VALUES (
                'analytics_refresh',
                '{"mode":"incremental","analytics_run_id":"first-run",'
                '"generation":"old"}'::jsonb,
                'analytics-refresh:ledger'
            )
            """
        )
    claimed_incremental = repository.claim_next_job(timeout_seconds=60)
    if claimed_incremental is None:
        raise AssertionError("incremental analytics refresh could not be claimed")
    _expect_equal(
        claimed_incremental.payload,
        {
            "mode": "incremental",
            "analytics_run_id": "first-run",
            "generation": "old",
        },
        "claimed incremental analytics payload",
    )

    repository.enqueue_analytics_refresh_job(mode="full")
    with psycopg.connect(database_url) as connection:
        promoted_claimed = connection.execute(
            """
            SELECT status, payload
            FROM job
            WHERE id = %s
            """,
            (claimed_incremental.id,),
        ).fetchone()
    _expect_equal(
        promoted_claimed,
        (
            "claimed",
            {
                "mode": "full",
                "analytics_run_id": "first-run",
                "generation": "old",
                "rerun_requested": True,
            },
        ),
        "claimed analytics mode promotion",
    )

    repository.complete_job(claimed_incremental, {"accepted": True}, needs_ai=False)
    with psycopg.connect(database_url) as connection:
        queued_rerun = connection.execute(
            """
            SELECT status, payload, claim_token, claimed_at, finished_at
            FROM job
            WHERE id = %s
            """,
            (claimed_incremental.id,),
        ).fetchone()
    _expect_equal(
        queued_rerun,
        ("queued", {"mode": "full"}, None, None, None),
        "coalesced full analytics rerun",
    )
    rerun = repository.claim_next_job(timeout_seconds=60)
    if rerun is None:
        raise AssertionError("coalesced full analytics rerun could not be claimed")
    _expect_equal(rerun.payload, {"mode": "full"}, "full rerun claim payload")
    repository.complete_job(rerun, {"accepted": True}, needs_ai=False)


def execute_acceptance(arguments: argparse.Namespace) -> AcceptanceResult:
    migrations = load_migrations()
    phase1_migrations = migrations[:PHASE1_MIGRATION_COUNT]
    phase2_migrations = migrations[PHASE1_MIGRATION_COUNT:]
    token = uuid4().hex[:20]
    cad_database = f"{DATABASE_PREFIX}cad_{token}"
    pending_database = f"{DATABASE_PREFIX}pending_{token}"
    database_names = (cad_database, pending_database)
    created_databases: list[str] = []
    primary_error: BaseException | None = None
    try:
        create_database(arguments.admin_url, cad_database)
        created_databases.append(cad_database)
        cad_url = disposable_database_url(arguments.admin_url, cad_database)
        apply_migrations(cad_url, phase1_migrations)
        seed_legacy_cad(cad_url)
        apply_migrations(cad_url, phase2_migrations)
        assert_cad_backfill(cad_url)
        cad_jobs = assert_phase2_jobs(cad_url)

        rollback_migrations(cad_url, tuple(reversed(phase2_migrations)))
        assert_phase1_rollback(cad_url)
        apply_migrations(cad_url, phase2_migrations)
        assert_cad_backfill(cad_url)
        _expect_equal(
            assert_phase2_jobs(cad_url), cad_jobs, "jobs after Phase 2 reapply"
        )
        currency_guard_sqlstates = assert_currency_guards_and_pending_insert(cad_url)
        assert_analytics_mode_promotion(cad_url)

        create_database(arguments.admin_url, pending_database)
        created_databases.append(pending_database)
        pending_url = disposable_database_url(arguments.admin_url, pending_database)
        apply_migrations(pending_url, phase1_migrations)
        seed_legacy_pending(pending_url)
        apply_migrations(pending_url, phase2_migrations)
        assert_pending_upgrade(pending_url)
        pending_jobs = assert_phase2_jobs(pending_url)
        _expect_equal(pending_jobs, cad_jobs, "pending-upgrade queued jobs")

        return AcceptanceResult(
            migration_count=len(migrations),
            disposable_database_count=len(database_names),
            cad_backfill_preserved=True,
            rollback_reapply_succeeded=True,
            currency_guard_sqlstates=currency_guard_sqlstates,
            pending_native_preserved=True,
            queued_job_kinds=pending_jobs,
            analytics_mode_promotion_succeeded=True,
        )
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for database_name in reversed(created_databases):
            try:
                drop_database(arguments.admin_url, database_name)
            except psycopg.Error as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            details = "; ".join(str(error) for error in cleanup_errors)
            if primary_error is not None:
                primary_error.add_note(
                    f"disposable database cleanup also failed: {details}"
                )
            else:
                raise RuntimeError(f"disposable database cleanup failed: {details}")


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = parse_arguments(arguments)
    result = execute_acceptance(parsed)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
