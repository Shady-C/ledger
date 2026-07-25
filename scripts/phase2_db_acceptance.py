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
import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
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
    "202607240014_add_market_scopes.sql",
    "202607240015_add_configurable_home_currency.sql",
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
    market_scope_guards_succeeded: bool
    market_recurring_collision_guard_succeeded: bool
    scoped_materialization_succeeded: bool
    legacy_review_state_preserved: bool
    legacy_review_state_rollback_restored: bool
    home_currency_round_trip_succeeded: bool
    switch_audit_succeeded: bool
    currency_fenced_publication_succeeded: bool
    active_tzs_rollback_refused: bool


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


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def seed_legacy_review_state(database_url: str) -> None:
    """Seed reviewed Phase 2 rows before market scopes exist."""

    recurring_fingerprint = _fingerprint(
        "recurring", "legacy-merchant", "spend", "base", "CAD"
    )
    with psycopg.connect(database_url) as connection:
        run = connection.execute(
            """
            INSERT INTO analytics_run (
                id, mode, status, started_at, finished_at, result
            ) VALUES (
                '40000000-0000-4000-8000-000000000001',
                'full', 'succeeded', now(), now(), '{}'::jsonb
            )
            RETURNING generation
            """
        ).fetchone()
        if run is None:
            raise AssertionError("could not seed legacy analytics generation")
        generation = run[0]
        connection.execute(
            """
            INSERT INTO recurring_series (
                id, detector_fingerprint, merchant_key, flow_type, status,
                detected_cadence, cadence_override, comparison_basis,
                comparison_currency, detected_expected_amount,
                expected_amount_override, detected_next_date, confidence,
                first_occurrence_date, latest_occurrence_date,
                last_detected_generation, reviewed_at
            ) VALUES (
                '50000000-0000-4000-8000-000000000001',
                %s, 'legacy-merchant', 'spend', 'confirmed',
                'monthly', 'quarterly', 'base', 'CAD', 40.00, 45.00,
                DATE '2026-03-01', 0.9500,
                DATE '2026-01-01', DATE '2026-02-01', %s, now()
            )
            """,
            (recurring_fingerprint, generation),
        )
        connection.execute(
            """
            INSERT INTO insight_finding (
                id, detector_fingerprint, finding_type, severity, status,
                headline, evidence, recurring_series_id,
                last_detected_generation, reviewed_at
            ) VALUES
              (
                '60000000-0000-4000-8000-000000000001',
                'legacy-native-fingerprint', 'unusual_frequency', 'warning',
                'dismissed', 'Legacy native finding',
                '{"transactionCount":4}'::jsonb, NULL, %s, now()
              ),
              (
                '60000000-0000-4000-8000-000000000002',
                'legacy-overdue-fingerprint', 'recurring_overdue', 'warning',
                'confirmed', 'Legacy overdue finding',
                '{"expectedNextDate":"2026-03-01"}'::jsonb,
                '50000000-0000-4000-8000-000000000001', %s, now()
              ),
              (
                '60000000-0000-4000-8000-000000000003',
                'legacy-base-fingerprint', 'unusual_amount', 'warning',
                'dismissed', 'Legacy reporting-valued finding',
                '{"difference":"35.00"}'::jsonb, NULL, %s, now()
              )
            """,
            (generation, generation, generation),
        )


def assert_market_recurring_collision_preflight(
    database_url: str,
    *,
    market_migration_up_sql: str,
) -> None:
    """Reject dirty legacy rows that would collapse onto one reviewed identity."""

    dirty_id = "50000000-0000-4000-8000-000000000002"
    with psycopg.connect(database_url) as connection:
        generation = connection.execute(
            """
            SELECT last_detected_generation
            FROM recurring_series
            WHERE id = '50000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        if generation is None:
            raise AssertionError("legacy recurring generation is missing")
        connection.execute(
            """
            INSERT INTO recurring_series (
                id, detector_fingerprint, merchant_key, flow_type, status,
                detected_cadence, comparison_basis, comparison_currency,
                detected_expected_amount, detected_next_date, confidence,
                first_occurrence_date, latest_occurrence_date,
                last_detected_generation
            ) VALUES (
                %s, %s, 'legacy-merchant', 'spend', 'detected',
                'monthly', 'base', 'TZS', 80000.00, DATE '2026-03-01', 0.9000,
                DATE '2026-01-01', DATE '2026-02-01', %s
            )
            """,
            (
                dirty_id,
                _fingerprint(
                    "recurring",
                    "legacy-merchant",
                    "spend",
                    "base",
                    "TZS",
                ),
                generation[0],
            ),
        )

    with psycopg.connect(database_url, autocommit=True) as connection:
        try:
            with connection.transaction():
                connection.execute(market_migration_up_sql)
        except psycopg.errors.CheckViolation as error:
            _expect_equal(
                error.sqlstate,
                "23514",
                "recurring fingerprint collision SQLSTATE",
            )
        else:
            raise AssertionError("market migration accepted colliding recurring identities")

    with psycopg.connect(database_url) as connection:
        market_column = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'recurring_series'
              AND column_name = 'market_scope'
            """
        ).fetchone()
        connection.execute("DELETE FROM recurring_series WHERE id = %s", (dirty_id,))
    _expect_equal(
        market_column,
        None,
        "market migration rollback after recurring collision",
    )


def assert_market_migration_preserves_review_state(database_url: str) -> None:
    scoped_series_fingerprint = _fingerprint(
        "ALL",
        "recurring",
        "legacy-merchant",
        "spend",
        "base",
        "CAD",
        "materiality-v1",
    )
    overdue_source_fingerprint = _fingerprint(
        "recurring_overdue", scoped_series_fingerprint, "2026-03-01"
    )
    with psycopg.connect(database_url) as connection:
        series = connection.execute(
            """
            SELECT id::text, detector_fingerprint, market_scope, status,
                   cadence_override, expected_amount_override, reviewed_at IS NOT NULL
            FROM recurring_series
            WHERE id = '50000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        findings = connection.execute(
            """
            SELECT id::text, detector_fingerprint, market_scope, status,
                   reviewed_at IS NOT NULL, resolved_at IS NOT NULL,
                   evidence
            FROM insight_finding
            WHERE id IN (
                '60000000-0000-4000-8000-000000000001',
                '60000000-0000-4000-8000-000000000002',
                '60000000-0000-4000-8000-000000000003'
            )
            ORDER BY id
            """
        ).fetchall()

    _expect_equal(
        series,
        (
            "50000000-0000-4000-8000-000000000001",
            scoped_series_fingerprint,
            "ALL",
            "confirmed",
            "quarterly",
            Decimal("45.00"),
            True,
        ),
        "scoped recurring review state",
    )
    _expect_equal(len(findings), 3, "scoped legacy finding count")
    expected = (
        (
            "60000000-0000-4000-8000-000000000001",
            _fingerprint("ALL", "legacy-native-fingerprint"),
            "ALL",
            "dismissed",
            True,
            False,
        ),
        (
            "60000000-0000-4000-8000-000000000002",
            _fingerprint("ALL", overdue_source_fingerprint),
            "ALL",
            "confirmed",
            True,
            False,
        ),
        (
            "60000000-0000-4000-8000-000000000003",
            _fingerprint(
                "ALL", "CAD", "materiality-v1", "legacy", "legacy-base-fingerprint"
            ),
            "ALL",
            "resolved",
            True,
            True,
        ),
    )
    for actual, expected_prefix in zip(findings, expected, strict=True):
        _expect_equal(actual[:6], expected_prefix, f"scoped finding {actual[0]}")
        evidence = actual[6]
        if not isinstance(evidence, dict):
            raise TypeError("scoped finding evidence was not returned as an object")
        _expect_equal(
            evidence.get("_migration014DetectorFingerprint"),
            {
                "60000000-0000-4000-8000-000000000001": "legacy-native-fingerprint",
                "60000000-0000-4000-8000-000000000002": "legacy-overdue-fingerprint",
                "60000000-0000-4000-8000-000000000003": "legacy-base-fingerprint",
            }[actual[0]],
            f"rollback fingerprint evidence {actual[0]}",
        )


def assert_market_rollback_restores_review_identity(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        series = connection.execute(
            """
            SELECT id::text, detector_fingerprint, status, cadence_override,
                   expected_amount_override, reviewed_at IS NOT NULL
            FROM recurring_series
            WHERE id = '50000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        findings = connection.execute(
            """
            SELECT id::text, detector_fingerprint, status,
                   reviewed_at IS NOT NULL, resolved_at IS NOT NULL, evidence
            FROM insight_finding
            WHERE id IN (
                '60000000-0000-4000-8000-000000000001',
                '60000000-0000-4000-8000-000000000002',
                '60000000-0000-4000-8000-000000000003'
            )
            ORDER BY id
            """
        ).fetchall()
    _expect_equal(
        series,
        (
            "50000000-0000-4000-8000-000000000001",
            _fingerprint("recurring", "legacy-merchant", "spend", "base", "CAD"),
            "confirmed",
            "quarterly",
            Decimal("45.00"),
            True,
        ),
        "rolled-back recurring review identity",
    )
    _expect_equal(
        [(row[0], row[1], row[2], row[3]) for row in findings],
        [
            (
                "60000000-0000-4000-8000-000000000001",
                "legacy-native-fingerprint",
                "dismissed",
                True,
            ),
            (
                "60000000-0000-4000-8000-000000000002",
                "legacy-overdue-fingerprint",
                "confirmed",
                True,
            ),
            (
                "60000000-0000-4000-8000-000000000003",
                "legacy-base-fingerprint",
                "resolved",
                True,
            ),
        ],
        "rolled-back finding review identities",
    )
    for row in findings:
        evidence = row[5]
        if not isinstance(evidence, dict):
            raise TypeError(
                "rolled-back finding evidence was not returned as an object"
            )
        if any(key.startswith("_migration014") for key in evidence):
            raise AssertionError("private market migration evidence survived rollback")


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
            INSERT INTO account (
                id, display_name, kind, native_currency, market_code
            )
            VALUES
              (
                '11000000-0000-4000-8000-000000000001',
                'TZS account', 'chequing', 'TZS', 'TZ'
              ),
              (
                '11000000-0000-4000-8000-000000000002',
                'USD account', 'chequing', 'USD', 'TZ'
              );

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


def assert_market_scope_guards_and_refresh(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        legacy_market = connection.execute(
            """
            SELECT market_code
            FROM account
            WHERE id = '10000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        market_profile = connection.execute(
            "SELECT market_profile FROM ledger_settings WHERE singleton"
        ).fetchone()
        _expect_equal(legacy_market, (None,), "legacy account market assignment")
        _expect_equal(market_profile, (None,), "initial market profile")

        _assert_check_violation(
            connection,
            """
            INSERT INTO account (display_name, kind, native_currency)
            VALUES ('Missing market', 'chequing', 'CAD')
            """,
            "new account without market",
        )
        _assert_check_violation(
            connection,
            """
            INSERT INTO account (
                display_name, kind, native_currency, market_code
            ) VALUES ('Invalid market', 'chequing', 'CAD', 'US')
            """,
            "new account with unsupported market",
        )

        connection.execute(
            """
            UPDATE account
            SET market_code = 'CA', updated_at = now()
            WHERE id = '10000000-0000-4000-8000-000000000001'
            """
        )
        refresh = connection.execute(
            """
            SELECT status, payload
            FROM job
            WHERE kind = 'analytics_refresh'
              AND status IN ('queued', 'claimed')
            """
        ).fetchone()
        _expect_equal(
            refresh,
            ("queued", {"mode": "full", "rerun_requested": True}),
            "market reassignment analytics promotion",
        )

        connection.execute(
            """
            UPDATE job
            SET status = 'done',
                claimed_at = COALESCE(claimed_at, now()),
                finished_at = now(),
                updated_at = now()
            WHERE kind = 'analytics_refresh'
              AND status = 'queued'
            """
        )
        connection.execute(
            """
            UPDATE account
            SET market_code = 'TZ', updated_at = now()
            WHERE id = '10000000-0000-4000-8000-000000000001'
            """
        )
        replacement = connection.execute(
            """
            SELECT status, payload
            FROM job
            WHERE kind = 'analytics_refresh'
              AND status IN ('queued', 'claimed')
            """
        ).fetchone()
        _expect_equal(
            replacement,
            ("queued", {"mode": "full"}),
            "market reassignment after active-job turnover",
        )


def assert_scoped_materialization(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        run = connection.execute(
            """
            INSERT INTO analytics_run (
                mode, status, started_at, base_currency,
                threshold_policy_version
            ) VALUES (
                'full', 'running', now(), 'CAD', 'materiality-v1'
            )
            RETURNING id::text, generation
            """
        ).fetchone()
        if run is None:
            raise AssertionError("could not create scoped analytics run")
        run_id, generation = run

        connection.execute(
            """
            INSERT INTO analytics_monthly_aggregate (
                generation, period_start, dimension_type, market_scope,
                currency_base, transaction_count, valued_count
            ) VALUES
              (%s, DATE '2026-01-01', 'ledger', 'ALL', 'CAD', 1, 1),
              (%s, DATE '2026-01-01', 'ledger', 'CA', 'CAD', 1, 1)
            """,
            (generation, generation),
        )

        series_rows = connection.execute(
            """
            INSERT INTO recurring_series (
                detector_fingerprint, merchant_key, flow_type,
                detected_cadence, comparison_basis, comparison_currency,
                detected_expected_amount, detected_next_date, confidence,
                first_occurrence_date, latest_occurrence_date,
                last_detected_generation, market_scope
            ) VALUES
              (
                'acceptance-shared-series', 'shared-merchant', 'spend',
                'monthly', 'native', 'CAD', 123.45,
                DATE '2026-02-02', 1,
                DATE '2026-01-02', DATE '2026-01-02', %s, 'ALL'
              ),
              (
                'acceptance-shared-series', 'shared-merchant', 'spend',
                'monthly', 'native', 'CAD', 123.45,
                DATE '2026-02-02', 1,
                DATE '2026-01-02', DATE '2026-01-02', %s, 'CA'
              )
            RETURNING id::text, market_scope
            """,
            (generation, generation),
        ).fetchall()
        series_by_scope = {
            str(scope): str(series_id) for series_id, scope in series_rows
        }

        for scope in ("ALL", "CA"):
            connection.execute(
                """
                INSERT INTO recurring_occurrence (
                    series_id, transaction_id, occurrence_number,
                    occurrence_date, comparison_amount, comparison_currency,
                    comparison_basis, detected_generation
                ) VALUES (
                    %s,
                    '30000000-0000-4000-8000-000000000001',
                    1, DATE '2026-01-02', 123.45, 'CAD', 'native', %s
                )
                """,
                (series_by_scope[scope], generation),
            )

        connection.execute(
            """
            INSERT INTO insight_finding (
                detector_fingerprint, finding_type, severity, headline,
                evidence, last_detected_generation, market_scope
            ) VALUES
              (
                'acceptance-shared-finding', 'unusual_amount', 'warning',
                'Scoped finding', '{}'::jsonb, %s, 'ALL'
              ),
              (
                'acceptance-shared-finding', 'unusual_amount', 'warning',
                'Scoped finding', '{}'::jsonb, %s, 'CA'
              )
            """,
            (generation, generation),
        )
        published = connection.execute(
            "SELECT publish_analytics_generation(%s, '{}'::jsonb)",
            (run_id,),
        ).fetchone()
        _expect_equal(published, (generation,), "scoped analytics publication")

    with psycopg.connect(database_url) as connection:
        current_scopes = connection.execute(
            """
            SELECT market_scope
            FROM analytics_monthly_current
            ORDER BY market_scope
            """
        ).fetchall()
        occurrence_count = connection.execute(
            """
            SELECT count(*)
            FROM recurring_occurrence
            WHERE transaction_id = '30000000-0000-4000-8000-000000000001'
            """
        ).fetchone()
        finding_scopes = connection.execute(
            """
            SELECT market_scope
            FROM insight_finding
            WHERE detector_fingerprint = 'acceptance-shared-finding'
            ORDER BY market_scope
            """
        ).fetchall()
    _expect_equal(current_scopes, [("ALL",), ("CA",)], "current aggregate scopes")
    _expect_equal(occurrence_count, (2,), "cross-scope recurring occurrences")
    _expect_equal(finding_scopes, [("ALL",), ("CA",)], "finding scopes")


def _rewrite_reporting_currency(
    database_url: str,
    *,
    target_currency: str,
) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            UPDATE ledger_settings
            SET base_currency = %s, updated_at = now()
            WHERE singleton
            """,
            (target_currency,),
        )
        connection.execute(
            """
            UPDATE txn
            SET currency_base = %s,
                amount_base = CASE
                    WHEN currency_native = %s THEN amount_native
                    ELSE NULL
                END,
                fx_rate = CASE
                    WHEN currency_native = %s THEN 1
                    ELSE NULL
                END,
                fx_rate_date = CASE
                    WHEN currency_native = %s THEN booked_date
                    ELSE NULL
                END,
                enrichment = enrichment - 'fx_source',
                updated_at = now()
            """,
            (
                target_currency,
                target_currency,
                target_currency,
                target_currency,
            ),
        )


def assert_home_currency_round_trip(
    database_url: str,
    *,
    configurable_currency_down_sql: str,
) -> None:
    with psycopg.connect(database_url) as connection:
        defaults = connection.execute(
            """
            SELECT table_name, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (table_name, column_name) IN (
                  ('ledger_settings', 'base_currency'),
                  ('txn', 'currency_base'),
                  ('analytics_monthly_aggregate', 'currency_base')
              )
            ORDER BY table_name
            """
        ).fetchall()
        profile = connection.execute(
            """
            SELECT policy_version, minimum_difference_low,
                   minimum_difference_balanced, minimum_difference_high,
                   minimum_price_increase, source_currency,
                   source_rate, source_rate_date
            FROM analytics_threshold_profile
            WHERE base_currency = 'CAD'
            """
        ).fetchone()
    _expect_equal(
        defaults,
        [
            ("analytics_monthly_aggregate", None),
            ("ledger_settings", None),
            ("txn", None),
        ],
        "reporting currency defaults",
    )
    _expect_equal(
        profile,
        (
            "materiality-v1",
            Decimal("25.00"),
            Decimal("10.00"),
            Decimal("5.00"),
            Decimal("1.00"),
            None,
            None,
            None,
        ),
        "seeded CAD threshold profile",
    )

    with psycopg.connect(database_url, autocommit=True) as connection:
        _assert_check_violation(
            connection,
            """
            UPDATE analytics_threshold_profile
            SET minimum_difference_balanced = 11.00
            WHERE base_currency = 'CAD'
            """,
            "frozen CAD threshold profile",
        )

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO analytics_threshold_profile (
                base_currency, policy_version,
                minimum_difference_low, minimum_difference_balanced,
                minimum_difference_high, minimum_price_increase,
                source_currency, source_rate, source_rate_date
            ) VALUES (
                'TZS', 'materiality-v1',
                50000.00, 20000.00, 10000.00, 2000.00,
                'CAD', 2000.00000000, CURRENT_DATE
            )
            """
        )

    _rewrite_reporting_currency(database_url, target_currency="TZS")

    with psycopg.connect(database_url) as connection:
        settings = connection.execute(
            """
            SELECT ledger.base_currency, analytics.published_generation
            FROM ledger_settings AS ledger
            CROSS JOIN analytics_settings AS analytics
            WHERE ledger.singleton AND analytics.singleton
            """
        ).fetchone()
        values = connection.execute(
            """
            SELECT currency_native, amount_native, currency_base,
                   amount_base, fx_rate, fx_rate_date
            FROM txn
            WHERE id IN (
                '30000000-0000-4000-8000-000000000001',
                '31000000-0000-4000-8000-000000000001'
            )
            ORDER BY id
            """
        ).fetchall()
    _expect_equal(settings, ("TZS", None), "TZS switch publication state")
    _expect_equal(
        values,
        [
            ("CAD", Decimal("123.45"), "TZS", None, None, None),
            (
                "TZS",
                Decimal("-100000.00"),
                "TZS",
                Decimal("-100000.00"),
                Decimal("1.00000000"),
                date(2026, 2, 3),
            ),
        ],
        "TZS reporting rebuild from native values",
    )

    with psycopg.connect(database_url) as connection:
        try:
            connection.execute(configurable_currency_down_sql)
        except psycopg.errors.CheckViolation as error:
            _expect_equal(error.sqlstate, "23514", "active TZS rollback SQLSTATE")
            connection.rollback()
        else:
            raise AssertionError("configurable-currency rollback accepted active TZS")

    with psycopg.connect(database_url) as connection:
        tzs_run = connection.execute(
            """
            INSERT INTO analytics_run (
                mode, status, started_at, base_currency,
                threshold_policy_version
            ) VALUES (
                'full', 'running', now(), 'TZS', 'materiality-v1'
            )
            RETURNING id::text, generation
            """
        ).fetchone()
        cad_run = connection.execute(
            """
            INSERT INTO analytics_run (
                mode, status, started_at, base_currency,
                threshold_policy_version
            ) VALUES (
                'full', 'running', now(), 'CAD', 'materiality-v1'
            )
            RETURNING id::text
            """
        ).fetchone()
        if tzs_run is None or cad_run is None:
            raise AssertionError("could not create currency-fence acceptance runs")
        tzs_run_id, tzs_generation = tzs_run
        connection.execute(
            """
            INSERT INTO analytics_monthly_aggregate (
                generation, period_start, dimension_type, market_scope,
                currency_base
            ) VALUES (%s, DATE '2026-02-01', 'ledger', 'ALL', 'TZS')
            """,
            (tzs_generation,),
        )
        published = connection.execute(
            "SELECT publish_analytics_generation(%s, '{}'::jsonb)",
            (tzs_run_id,),
        ).fetchone()
        _expect_equal(published, (tzs_generation,), "TZS analytics publication")

    with psycopg.connect(database_url, autocommit=True) as connection:
        _assert_check_violation(
            connection,
            "SELECT publish_analytics_generation('" + cad_run[0] + "', '{}'::jsonb)",
            "mismatched CAD analytics publication",
        )

    _rewrite_reporting_currency(database_url, target_currency="CAD")

    with psycopg.connect(database_url) as connection:
        settings = connection.execute(
            """
            SELECT ledger.base_currency, analytics.published_generation
            FROM ledger_settings AS ledger
            CROSS JOIN analytics_settings AS analytics
            WHERE ledger.singleton AND analytics.singleton
            """
        ).fetchone()
        values = connection.execute(
            """
            SELECT currency_native, amount_native, currency_base,
                   amount_base, fx_rate, fx_rate_date
            FROM txn
            WHERE id IN (
                '30000000-0000-4000-8000-000000000001',
                '31000000-0000-4000-8000-000000000001'
            )
            ORDER BY id
            """
        ).fetchall()
    _expect_equal(settings, ("CAD", None), "CAD return publication state")
    _expect_equal(
        values,
        [
            (
                "CAD",
                Decimal("123.45"),
                "CAD",
                Decimal("123.45"),
                Decimal("1.00000000"),
                date(2026, 1, 2),
            ),
            ("TZS", Decimal("-100000.00"), "CAD", None, None, None),
        ],
        "CAD reporting rebuild from native values",
    )


def assert_switch_audit_and_override_conversion(database_url: str) -> None:
    """Prove every switch and recurring override share one durable quote."""

    series_id = "51000000-0000-4000-8000-000000000001"
    overdue_id = "61000000-0000-4000-8000-000000000001"
    price_increase_id = "61000000-0000-4000-8000-000000000002"
    merchant_key = "acceptance switch audit merchant"
    expected_next_date = "2026-04-01"
    stable_series = (
        (
            "52000000-0000-4000-8000-000000000001",
            _fingerprint(
                "ALL",
                "recurring",
                "acceptance native stable",
                "spend",
                "native",
                "USD",
            ),
            "acceptance native stable",
            "native",
            "USD",
        ),
        (
            "52000000-0000-4000-8000-000000000002",
            _fingerprint(
                "ALL",
                "recurring",
                "acceptance original stable",
                "spend",
                "original",
                "EUR",
            ),
            "acceptance original stable",
            "original",
            "EUR",
        ),
    )
    initial_series_fingerprint = _fingerprint(
        "ALL",
        "recurring",
        merchant_key,
        "spend",
        "base",
        "CAD",
        "materiality-v1",
    )
    initial_overdue_fingerprint = _fingerprint(
        "ALL",
        _fingerprint(
            "recurring_overdue",
            initial_series_fingerprint,
            expected_next_date,
        ),
    )
    with psycopg.connect(database_url) as connection:
        run = connection.execute(
            """
            SELECT generation
            FROM analytics_run
            WHERE base_currency = 'CAD'
            ORDER BY generation DESC
            LIMIT 1
            """
        ).fetchone()
        if run is None:
            raise AssertionError("switch-audit acceptance run is missing")
        connection.execute(
            """
            INSERT INTO recurring_series (
                id, detector_fingerprint, merchant_key, flow_type, status,
                detected_cadence, cadence_override,
                comparison_basis, comparison_currency,
                detected_expected_amount, expected_amount_override,
                detected_next_date, confidence, first_occurrence_date,
                latest_occurrence_date, last_detected_generation,
                reviewed_at, market_scope
            ) VALUES (
                %s, %s, %s,
                'spend', 'confirmed', 'monthly', 'quarterly', 'base', 'CAD',
                10.00, 12.34, DATE '2026-04-01', 0.9500,
                DATE '2026-01-01', DATE '2026-03-01', %s,
                now(), 'ALL'
            )
            """,
            (series_id, initial_series_fingerprint, merchant_key, run[0]),
        )
        connection.execute(
            """
            INSERT INTO insight_finding (
                id, detector_fingerprint, finding_type, severity, status,
                headline, evidence, recurring_series_id,
                last_detected_generation, reviewed_at, market_scope
            ) VALUES (
                %s, %s, 'recurring_overdue', 'info', 'confirmed',
                'Acceptance recurring item is overdue',
                jsonb_build_object(
                    'expectedNextDate', %s::text,
                    'baseCurrency', 'CAD',
                    'thresholdPolicyVersion', 'materiality-v1'
                ),
                %s, %s, now(), 'ALL'
            )
            """,
            (
                overdue_id,
                initial_overdue_fingerprint,
                expected_next_date,
                series_id,
                run[0],
            ),
        )
        connection.execute(
            """
            INSERT INTO insight_finding (
                id, detector_fingerprint, finding_type, severity, status,
                headline, evidence, recurring_series_id,
                last_detected_generation, reviewed_at, market_scope
            ) VALUES (
                %s, %s, 'recurring_price_increase', 'warning', 'dismissed',
                'Acceptance recurring price increased',
                jsonb_build_object(
                    'comparisonCurrency', 'CAD',
                    'baseCurrency', 'CAD',
                    'thresholdPolicyVersion', 'materiality-v1'
                ),
                %s, %s, now(), 'ALL'
            )
            """,
            (
                price_increase_id,
                _fingerprint(
                    "ALL",
                    "CAD",
                    "materiality-v1",
                    _fingerprint(
                        "recurring_price_increase",
                        initial_series_fingerprint,
                        "acceptance-price-increase",
                        "10.00",
                        "12.00",
                    ),
                ),
                series_id,
                run[0],
            ),
        )
        for stable_id, fingerprint, stable_merchant, basis, currency in stable_series:
            connection.execute(
                """
                INSERT INTO recurring_series (
                    id, detector_fingerprint, merchant_key, flow_type, status,
                    detected_cadence, cadence_override,
                    comparison_basis, comparison_currency,
                    detected_expected_amount, detected_next_date, confidence,
                    first_occurrence_date, latest_occurrence_date,
                    last_detected_generation, reviewed_at, market_scope
                ) VALUES (
                    %s, %s, %s, 'spend', 'confirmed', 'monthly', 'quarterly',
                    %s, %s, 5.00, DATE '2026-04-01', 0.9500,
                    DATE '2026-01-01', DATE '2026-03-01', %s, now(), 'ALL'
                )
                """,
                (
                    stable_id,
                    fingerprint,
                    stable_merchant,
                    basis,
                    currency,
                    run[0],
                ),
            )
        today = connection.execute("SELECT CURRENT_DATE").fetchone()
        if today is None:
            raise AssertionError("database current date is missing")
        rate_date = today[0]
        connection.execute(
            """
            INSERT INTO fx_rate (base, quote, as_of, rate, source)
            VALUES
                ('CAD', 'TZS', %s, 1850.12345678, 'acceptance-cad-tzs'),
                ('TZS', 'CAD', %s, 0.00054000, 'acceptance-tzs-cad')
            ON CONFLICT (base, quote, as_of) DO UPDATE
            SET rate = EXCLUDED.rate,
                source = EXCLUDED.source,
                fetched_at = now()
            """,
            (rate_date, rate_date),
        )

    repository = PostgresRepository(database_url)
    current_override = Decimal("12.34")
    switches = (
        ("CAD", "TZS", Decimal("1850.12345678"), "acceptance-cad-tzs"),
        ("TZS", "CAD", Decimal("0.00054000"), "acceptance-tzs-cad"),
        ("CAD", "TZS", Decimal("1850.12345678"), "acceptance-cad-tzs"),
        ("TZS", "CAD", Decimal("0.00054000"), "acceptance-tzs-cad"),
    )
    for expected_id, (previous, target, rate, source) in enumerate(switches, start=1):
        repository.rebuild_base_currency(
            target_currency=target,
            max_staleness_days=7,
            allow_currency_change=True,
        )
        with psycopg.connect(database_url) as connection:
            evidence = connection.execute(
                """
                SELECT id, previous_currency, target_currency,
                       conversion_rate, rate_source, rate_source_date,
                       threshold_policy_version, switched_at IS NOT NULL
                FROM home_currency_switch_audit
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            series = connection.execute(
                """
                SELECT detector_fingerprint, expected_amount_override,
                       comparison_currency, status, cadence_override,
                       reviewed_at IS NOT NULL
                FROM recurring_series
                WHERE id = %s
                """,
                (series_id,),
            ).fetchone()
            overdue = connection.execute(
                """
                SELECT detector_fingerprint, status,
                       evidence ->> 'baseCurrency',
                       evidence ->> 'thresholdPolicyVersion',
                       reviewed_at IS NOT NULL
                FROM insight_finding
                WHERE id = %s
                """,
                (overdue_id,),
            ).fetchone()
            stable = connection.execute(
                """
                SELECT id::text, detector_fingerprint, status,
                       cadence_override, comparison_basis, comparison_currency,
                       reviewed_at IS NOT NULL
                FROM recurring_series
                WHERE id = ANY(%s::uuid[])
                ORDER BY id
                """,
                ([row[0] for row in stable_series],),
            ).fetchall()
            price_increase = connection.execute(
                """
                SELECT status, resolved_at IS NOT NULL, reviewed_at IS NOT NULL
                FROM insight_finding
                WHERE id = %s
                """,
                (price_increase_id,),
            ).fetchone()
        if (
            evidence is None
            or series is None
            or overdue is None
            or price_increase is None
        ):
            raise AssertionError("switch evidence or recurring review state is missing")
        _expect_equal(
            evidence,
            (
                expected_id,
                previous,
                target,
                rate,
                source,
                rate_date,
                "materiality-v1",
                True,
            ),
            f"{previous}-to-{target} switch evidence {expected_id}",
        )
        current_override = (current_override * evidence[3]).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        expected_series_fingerprint = _fingerprint(
            "ALL",
            "recurring",
            merchant_key,
            "spend",
            "base",
            target,
            "materiality-v1",
        )
        _expect_equal(
            series,
            (
                expected_series_fingerprint,
                current_override,
                target,
                "confirmed",
                "quarterly",
                True,
            ),
            f"recurring identity and review state after switch {expected_id}",
        )
        _expect_equal(
            overdue,
            (
                _fingerprint(
                    "ALL",
                    _fingerprint(
                        "recurring_overdue",
                        expected_series_fingerprint,
                        expected_next_date,
                    ),
                ),
                "confirmed",
                target,
                "materiality-v1",
                True,
            ),
            f"native overdue review state after switch {expected_id}",
        )
        _expect_equal(
            stable,
            [
                (
                    stable_id,
                    fingerprint,
                    "confirmed",
                    "quarterly",
                    basis,
                    currency,
                    True,
                )
                for stable_id, fingerprint, _merchant, basis, currency in stable_series
            ],
            f"native and original recurring identities after switch {expected_id}",
        )
        _expect_equal(
            price_increase,
            ("resolved", True, True),
            f"base-valued finding archival after switch {expected_id}",
        )

    repository.rebuild_base_currency(
        target_currency="CAD",
        max_staleness_days=7,
        allow_currency_change=True,
    )
    with psycopg.connect(database_url) as connection:
        count = connection.execute(
            "SELECT count(*) FROM home_currency_switch_audit"
        ).fetchone()
    _expect_equal(count, (4,), "same-currency rebuild switch audit count")

    with psycopg.connect(database_url, autocommit=True) as connection:
        _assert_check_violation(
            connection,
            """
            UPDATE home_currency_switch_audit
            SET conversion_rate = conversion_rate + 1
            WHERE id = 1
            """,
            "immutable home-currency switch evidence",
        )


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
        apply_migrations(cad_url, phase2_migrations[:2])
        seed_legacy_review_state(cad_url)
        assert_market_recurring_collision_preflight(
            cad_url,
            market_migration_up_sql=phase2_migrations[2].up_sql,
        )
        apply_migrations(cad_url, phase2_migrations[2:])
        assert_cad_backfill(cad_url)
        cad_jobs = assert_phase2_jobs(cad_url)
        assert_market_migration_preserves_review_state(cad_url)

        rollback_migrations(cad_url, tuple(reversed(phase2_migrations[2:])))
        assert_market_rollback_restores_review_identity(cad_url)
        rollback_migrations(cad_url, tuple(reversed(phase2_migrations[:2])))
        assert_phase1_rollback(cad_url)
        apply_migrations(cad_url, phase2_migrations)
        assert_cad_backfill(cad_url)
        _expect_equal(
            assert_phase2_jobs(cad_url), cad_jobs, "jobs after Phase 2 reapply"
        )
        currency_guard_sqlstates = assert_currency_guards_and_pending_insert(cad_url)
        assert_market_scope_guards_and_refresh(cad_url)
        assert_scoped_materialization(cad_url)
        assert_analytics_mode_promotion(cad_url)
        configurable_currency_migration = next(
            migration
            for migration in migrations
            if migration.name == "202607240015_add_configurable_home_currency.sql"
        )
        assert_home_currency_round_trip(
            cad_url,
            configurable_currency_down_sql=configurable_currency_migration.down_sql,
        )
        assert_switch_audit_and_override_conversion(cad_url)

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
            market_scope_guards_succeeded=True,
            market_recurring_collision_guard_succeeded=True,
            scoped_materialization_succeeded=True,
            legacy_review_state_preserved=True,
            legacy_review_state_rollback_restored=True,
            home_currency_round_trip_succeeded=True,
            switch_audit_succeeded=True,
            currency_fenced_publication_succeeded=True,
            active_tzs_rollback_refused=True,
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
