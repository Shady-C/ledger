"""Run the Phase 2 analytics acceptance benchmark in a disposable database.

Prerequisite: a PostgreSQL 16 + pgvector server matching the development stack.
The default URL targets the local Docker Compose PostgreSQL service. Run with:

    uv run --project services/worker --extra dev \
      python scripts/phase2_analytics_benchmark.py

The script creates a uniquely named ``ledger_benchmark_*`` database, applies
the checked-in migrations, inserts exactly 100,000 synthetic transactions, runs
the production analytics refresh service, warms representative materialized
Insights reads and deterministic Phase 3 Ask-equivalent reads, verifies the
per-query and three-query-plan limits, and drops the database even when an
assertion fails.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from worker.analytics import (
    AnalyticsRefreshService,
    PostgresAnalyticsRepository,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = "postgresql://ledger:ledger_dev_password@localhost:5432/postgres"
DATABASE_PREFIX = "ledger_benchmark_"
DEFAULT_TRANSACTION_COUNT = 100_000
DEFAULT_REBUILD_LIMIT_SECONDS = 120.0
DEFAULT_READ_LIMIT_SECONDS = 1.0
DEFAULT_ASK_PLAN_LIMIT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ReadMeasurement:
    name: str
    runs: int
    minimum_ms: float
    median_ms: float
    maximum_ms: float


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    transaction_count: int
    rebuild_seconds: float
    rebuild_limit_seconds: float
    fx_rate_watermark_verified: bool
    aggregate_count: int
    recurring_series_count: int
    finding_count: int
    warm_read_limit_seconds: float
    warm_reads: tuple[ReadMeasurement, ...]
    ask_warm_query_limit_seconds: float
    ask_warm_queries: tuple[ReadMeasurement, ...]
    ask_three_query_plan_limit_seconds: float
    ask_three_query_plan: ReadMeasurement


@dataclass(frozen=True, slots=True)
class QuerySpec:
    name: str
    query: str
    parameters: tuple[object, ...]
    minimum_rows: int = 1


READ_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "summary",
        """
        SELECT
            COALESCE(SUM(inflow_base), 0),
            COALESCE(SUM(outflow_base), 0),
            COALESCE(SUM(spending_base), 0),
            COALESCE(SUM(net_base), 0),
            COALESCE(SUM(pending_fx_count), 0)
        FROM analytics_monthly_current
        WHERE dimension_type = 'ledger'
        """,
    ),
    (
        "trends",
        """
        SELECT period_start, inflow_base, outflow_base, spending_base, net_base,
               coverage_status, pending_fx_count
        FROM analytics_monthly_current
        WHERE dimension_type = 'ledger'
        ORDER BY period_start
        """,
    ),
    (
        "merchant_movers",
        """
        SELECT merchant_id, SUM(spending_base) AS spending
        FROM analytics_monthly_current
        WHERE dimension_type = 'merchant'
        GROUP BY merchant_id
        ORDER BY spending DESC, merchant_id
        LIMIT 25
        """,
    ),
    (
        "recurring",
        """
        SELECT series.id, series.status, series.detected_cadence,
               COALESCE(series.cadence_override, series.detected_cadence),
               COUNT(occurrence.transaction_id)
        FROM recurring_series AS series
        LEFT JOIN recurring_occurrence AS occurrence ON occurrence.series_id = series.id
        GROUP BY series.id
        ORDER BY series.updated_at DESC, series.id
        LIMIT 50
        """,
    ),
    (
        "findings",
        """
        SELECT id, finding_type, severity, status, headline, evidence
        FROM insight_finding
        WHERE status IN ('new', 'confirmed')
        ORDER BY last_seen_at DESC, id
        LIMIT 50
        """,
    ),
)


ASK_QUERY_SPECS: tuple[QuerySpec, ...] = (
    QuerySpec(
        name="ask_aggregate_category_comparison",
        query="""
        WITH selected AS (
            SELECT
                'current'::text AS bucket,
                COALESCE(c.id::text, 'uncategorized') AS dimension_id,
                COALESCE(c.name, 'Uncategorized') AS dimension_label,
                t.amount_base,
                t.currency_native,
                COALESCE(
                    NULLIF(t.enrichment #>> '{categorization,flow_type}', ''),
                    CASE
                        WHEN t.direction IN ('fee', 'interest') THEN 'fee'
                        WHEN t.direction = 'payment' THEN 'transfer'
                        WHEN t.direction = 'refund' THEN 'refund'
                        WHEN a.kind = 'credit_card' AND t.amount_native < 0 THEN 'refund'
                        WHEN a.kind = 'credit_card' THEN 'spend'
                        WHEN t.amount_native > 0 THEN 'income'
                        ELSE 'spend'
                    END
                ) AS flow_type
            FROM txn AS t
            JOIN account AS a ON a.id = t.account_id
            LEFT JOIN category AS c ON c.id = t.category_id
            WHERE t.booked_date BETWEEN %s::date AND %s::date
              AND t.updated_at <= %s::timestamptz
            UNION ALL
            SELECT
                'previous'::text AS bucket,
                COALESCE(c.id::text, 'uncategorized') AS dimension_id,
                COALESCE(c.name, 'Uncategorized') AS dimension_label,
                t.amount_base,
                t.currency_native,
                COALESCE(
                    NULLIF(t.enrichment #>> '{categorization,flow_type}', ''),
                    CASE
                        WHEN t.direction IN ('fee', 'interest') THEN 'fee'
                        WHEN t.direction = 'payment' THEN 'transfer'
                        WHEN t.direction = 'refund' THEN 'refund'
                        WHEN a.kind = 'credit_card' AND t.amount_native < 0 THEN 'refund'
                        WHEN a.kind = 'credit_card' THEN 'spend'
                        WHEN t.amount_native > 0 THEN 'income'
                        ELSE 'spend'
                    END
                ) AS flow_type
            FROM txn AS t
            JOIN account AS a ON a.id = t.account_id
            LEFT JOIN category AS c ON c.id = t.category_id
            WHERE t.booked_date BETWEEN %s::date AND %s::date
              AND t.updated_at <= %s::timestamptz
        ), grouped AS (
            SELECT
                bucket,
                dimension_id,
                dimension_label,
                COALESCE(
                    SUM(ABS(amount_base)) FILTER (
                        WHERE amount_base IS NOT NULL AND flow_type IN ('spend', 'fee')
                    ),
                    0
                ) - COALESCE(
                    SUM(ABS(amount_base)) FILTER (
                        WHERE amount_base IS NOT NULL AND flow_type = 'refund'
                    ),
                    0
                ) AS spending,
                COUNT(*)::int AS transaction_count,
                COUNT(*) FILTER (WHERE amount_base IS NOT NULL)::int AS valued_count,
                COUNT(*) FILTER (WHERE amount_base IS NULL)::int AS pending_fx_count
            FROM selected
            GROUP BY bucket, dimension_id, dimension_label
        ), current_coverage AS (
            SELECT
                COUNT(*) FILTER (WHERE amount_base IS NOT NULL)::int AS valued_count,
                COUNT(*) FILTER (WHERE amount_base IS NULL)::int AS pending_fx_count
            FROM selected
            WHERE bucket = 'current'
        ), pending_currency AS (
            SELECT COALESCE(
                jsonb_object_agg(currency_native, transaction_count),
                '{}'::jsonb
            ) AS pending_by_currency
            FROM (
                SELECT currency_native, COUNT(*)::int AS transaction_count
                FROM selected
                WHERE bucket = 'current' AND amount_base IS NULL
                GROUP BY currency_native
            ) AS pending
        ), comparison_keys AS (
            SELECT dimension_id, MAX(dimension_label) AS dimension_label
            FROM grouped
            GROUP BY dimension_id
        ), paired AS (
            SELECT
                comparison_keys.dimension_id,
                comparison_keys.dimension_label,
                COALESCE(current_values.spending, 0) AS spending,
                COALESCE(previous_values.spending, 0) AS previous_spending,
                COALESCE(current_values.transaction_count, 0)::int AS transaction_count,
                COALESCE(previous_values.transaction_count, 0)::int
                    AS previous_transaction_count,
                COALESCE(current_values.valued_count, 0)::int AS valued_count,
                COALESCE(current_values.pending_fx_count, 0)::int AS pending_fx_count
            FROM comparison_keys
            LEFT JOIN grouped AS current_values
              ON current_values.bucket = 'current'
             AND current_values.dimension_id = comparison_keys.dimension_id
            LEFT JOIN grouped AS previous_values
              ON previous_values.bucket = 'previous'
             AND previous_values.dimension_id = comparison_keys.dimension_id
        ), reported AS (
            SELECT
                paired.dimension_id,
                paired.dimension_label,
                ROUND(paired.spending, 2)::text AS spending,
                ROUND(paired.previous_spending, 2)::text AS previous_spending,
                ROUND(paired.spending - paired.previous_spending, 2)::text
                    AS spending_change,
                CASE
                    WHEN paired.previous_spending <> 0 THEN ROUND(
                        (paired.spending - paired.previous_spending)
                        / ABS(paired.previous_spending) * 100,
                        2
                    )::text
                END AS spending_change_percent,
                paired.transaction_count,
                paired.previous_transaction_count,
                paired.valued_count,
                paired.pending_fx_count,
                current_coverage.valued_count AS total_valued_count,
                current_coverage.pending_fx_count AS total_pending_fx_count,
                pending_currency.pending_by_currency,
                paired.spending - paired.previous_spending AS sort_value
            FROM paired
            CROSS JOIN current_coverage
            CROSS JOIN pending_currency
        )
        SELECT
            dimension_id,
            dimension_label,
            spending,
            previous_spending,
            spending_change,
            spending_change_percent,
            transaction_count,
            previous_transaction_count,
            valued_count,
            pending_fx_count,
            total_valued_count,
            total_pending_fx_count,
            pending_by_currency
        FROM reported
        ORDER BY ABS(sort_value) DESC, dimension_label
        LIMIT %s::int
        """,
        parameters=(
            "2025-01-01",
            "2025-12-31",
            "2100-01-01T00:00:00+00:00",
            "2024-01-01",
            "2024-12-31",
            "2100-01-01T00:00:00+00:00",
            21,
        ),
    ),
    QuerySpec(
        name="ask_seasonality",
        query="""
        SELECT
            EXTRACT(MONTH FROM period_start)::int AS month_number,
            ROUND(AVG(spending_base), 2)::text AS average_spending,
            ROUND(
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY spending_base)::numeric,
                2
            )::text AS median_spending,
            COUNT(*)::int AS observation_count
        FROM analytics_monthly_current
        WHERE dimension_type = 'ledger'
          AND market_scope = 'ALL'
          AND currency_base = 'CAD'
          AND period_start BETWEEN %s::date AND %s::date
        GROUP BY EXTRACT(MONTH FROM period_start)
        ORDER BY month_number
        """,
        parameters=("2023-01-01", "2025-12-31"),
    ),
    QuerySpec(
        name="ask_recurring",
        query="""
        SELECT
            series.id,
            series.status,
            COALESCE(series.cadence_override, series.detected_cadence) AS cadence,
            COALESCE(series.expected_amount_override, series.detected_expected_amount)::text,
            COALESCE(series.next_date_override, series.detected_next_date)::text,
            COUNT(occurrence.transaction_id)::int AS occurrence_count
        FROM recurring_series AS series
        JOIN analytics_settings AS settings
          ON settings.singleton
         AND settings.published_generation = series.last_detected_generation
        JOIN analytics_run AS run
          ON run.generation = series.last_detected_generation
         AND run.base_currency = 'CAD'
        LEFT JOIN recurring_occurrence AS occurrence ON occurrence.series_id = series.id
        WHERE series.market_scope = 'ALL'
          AND series.latest_occurrence_date BETWEEN %s::date AND %s::date
        GROUP BY series.id
        ORDER BY series.updated_at DESC, series.id
        LIMIT 20
        """,
        parameters=("2023-01-01", "2025-12-31"),
    ),
    QuerySpec(
        name="ask_findings",
        query="""
        SELECT finding.id, finding.finding_type, finding.severity,
               finding.status, finding.headline
        FROM insight_finding AS finding
        JOIN analytics_settings AS settings
          ON settings.singleton
         AND settings.published_generation = finding.last_detected_generation
        JOIN analytics_run AS run
          ON run.generation = finding.last_detected_generation
         AND run.base_currency = 'CAD'
        WHERE finding.market_scope = 'ALL'
          AND finding.last_seen_at::date BETWEEN %s::date AND %s::date
        ORDER BY finding.last_seen_at DESC, finding.id
        LIMIT 20
        """,
        parameters=("2023-01-01", "2100-01-01"),
    ),
    QuerySpec(
        name="ask_fx_summary",
        query="""
        WITH setting AS (
            SELECT base_currency
            FROM ledger_settings
            WHERE singleton
        ), evidence AS (
            SELECT
                t.id AS transaction_id,
                t.booked_date,
                ABS(t.original_amount) AS foreign_amount,
                t.original_currency AS foreign_currency,
                ABS(t.amount_native) AS charged_amount_native,
                GREATEST(
                    ABS(t.amount_native) - COALESCE(t.fx_fee_amount_native, 0),
                    0
                ) AS conversion_amount_native,
                CASE
                    WHEN t.is_fx_fee THEN ABS(t.amount_native)
                    ELSE COALESCE(t.fx_fee_amount_native, 0)
                END AS explicit_fee_native,
                a.native_currency,
                t.fx_rate AS native_to_base_rate,
                setting.base_currency
            FROM txn AS t
            JOIN account AS a ON a.id = t.account_id
            CROSS JOIN setting
            WHERE t.booked_date BETWEEN %s::date AND %s::date
              AND t.updated_at <= %s::timestamptz
              AND (
                  (t.original_amount IS NOT NULL AND t.original_currency IS NOT NULL)
                  OR t.fx_fee_amount_native IS NOT NULL
                  OR t.is_fx_fee
                  OR t.amount_base IS NULL
              )
        ), compared AS (
            SELECT
                evidence.*,
                CASE
                    WHEN evidence.foreign_amount IS NULL
                      OR evidence.foreign_amount = 0 THEN NULL
                    ELSE evidence.conversion_amount_native / evidence.foreign_amount
                END AS bank_applied_rate,
                market.rate AS market_rate
            FROM evidence
            LEFT JOIN LATERAL (
                SELECT rate
                FROM fx_rate
                WHERE base = evidence.foreign_currency
                  AND quote = evidence.native_currency
                  AND as_of <= evidence.booked_date
                  AND as_of >= evidence.booked_date - 7
                  AND fetched_at <= %s::timestamptz
                ORDER BY as_of DESC
                LIMIT 1
            ) AS market ON evidence.foreign_currency IS NOT NULL
                       AND evidence.foreign_currency <> evidence.native_currency
        ), fees AS (
            SELECT
                compared.*,
                CASE
                    WHEN foreign_currency IS NULL THEN NULL
                    WHEN foreign_currency = native_currency THEN 1
                    ELSE market_rate
                END AS resolved_market_rate
            FROM compared
        ), calculated AS (
            SELECT
                fees.*,
                CASE
                    WHEN resolved_market_rate IS NULL OR bank_applied_rate IS NULL
                        THEN NULL
                    ELSE ROUND(
                        (bank_applied_rate / resolved_market_rate - 1) * 100,
                        4
                    )
                END AS markup_percent,
                CASE
                    WHEN resolved_market_rate IS NULL OR bank_applied_rate IS NULL
                        THEN NULL
                    ELSE ROUND(
                        (bank_applied_rate - resolved_market_rate) * foreign_amount,
                        2
                    )
                END AS estimated_markup_native,
                CASE
                    WHEN native_to_base_rate IS NULL THEN NULL
                    ELSE ROUND(explicit_fee_native * native_to_base_rate, 2)
                END AS explicit_fee_base
            FROM fees
        ), valued AS (
            SELECT
                calculated.*,
                CASE
                    WHEN estimated_markup_native IS NULL
                      OR native_to_base_rate IS NULL THEN NULL
                    ELSE ROUND(estimated_markup_native * native_to_base_rate, 2)
                END AS estimated_markup_base,
                (
                    native_to_base_rate IS NULL
                    OR (
                        foreign_amount IS NOT NULL
                        AND (resolved_market_rate IS NULL OR native_to_base_rate IS NULL)
                    )
                ) AS missing_rate
            FROM calculated
        )
        SELECT
            COALESCE(SUM(
                explicit_fee_base
            ) FILTER (WHERE explicit_fee_base IS NOT NULL) OVER (), 0)::text
                AS total_explicit_fee_base,
            COALESCE(SUM(
                estimated_markup_base
            ) FILTER (WHERE estimated_markup_base IS NOT NULL) OVER (), 0)::text
                AS total_estimated_markup_base,
            COALESCE(SUM(
                COALESCE(explicit_fee_base, 0)
                + COALESCE(estimated_markup_base, 0)
            ) OVER (), 0)::text AS total_fx_cost_base,
            (COUNT(*) FILTER (WHERE missing_rate) OVER ())::int AS missing_rate_count,
            COUNT(*) OVER ()::int AS total_row_count
        FROM valued
        ORDER BY booked_date DESC, transaction_id DESC
        LIMIT %s::int
        """,
        parameters=(
            "2023-01-01",
            "2025-12-31",
            "2100-01-01T00:00:00+00:00",
            "2100-01-01T00:00:00+00:00",
            1,
        ),
    ),
    QuerySpec(
        name="ask_transactions",
        query="""
        SELECT
            t.id::text,
            t.booked_date::text,
            a.display_name,
            t.description_raw,
            m.canonical_name,
            c.name,
            t.amount_native::text,
            t.currency_native,
            t.amount_base::text,
            t.currency_base
        FROM txn AS t
        JOIN account AS a ON a.id = t.account_id
        LEFT JOIN merchant AS m ON m.id = t.merchant_id
        LEFT JOIN category AS c ON c.id = t.category_id
        WHERE t.booked_date BETWEEN %s::date AND %s::date
          AND t.updated_at <= %s::timestamptz
        ORDER BY t.booked_date DESC, t.id DESC
        LIMIT 20
        """,
        parameters=(
            "2023-01-01",
            "2025-12-31",
            "2100-01-01T00:00:00+00:00",
        ),
    ),
    QuerySpec(
        name="ask_analytics_context",
        query="""
        WITH fx_context AS (
            SELECT MAX(fetched_at) AS latest_rate_at
            FROM fx_rate
        )
        SELECT
            ledger.base_currency,
            run.generation,
            run.threshold_policy_version,
            run.source_watermark,
            (run.result ->> 'fx_rate_watermark')::timestamptz AS fx_rate_watermark,
            (
                GREATEST(
                    COALESCE((SELECT MAX(updated_at) FROM txn), '-infinity'::timestamptz),
                    COALESCE((SELECT MAX(updated_at) FROM statement), '-infinity'::timestamptz),
                    COALESCE((SELECT MAX(updated_at) FROM account), '-infinity'::timestamptz)
                ) > COALESCE(run.source_watermark, '-infinity'::timestamptz)
                OR (
                    fx_context.latest_rate_at IS NOT NULL
                    AND (
                        run.result ->> 'fx_rate_watermark' IS NULL
                        OR fx_context.latest_rate_at
                            > (run.result ->> 'fx_rate_watermark')::timestamptz
                    )
                )
            ) AS source_changed,
            (
                fx_context.latest_rate_at IS NOT NULL
                AND (
                    run.result ->> 'fx_rate_watermark' IS NULL
                    OR fx_context.latest_rate_at
                        > (run.result ->> 'fx_rate_watermark')::timestamptz
                )
            ) AS fx_rates_changed
        FROM ledger_settings AS ledger
        CROSS JOIN fx_context
        LEFT JOIN analytics_settings AS settings ON settings.singleton
        LEFT JOIN analytics_run AS run
          ON run.generation = settings.published_generation
         AND run.base_currency = ledger.base_currency
         AND run.status = 'succeeded'
        WHERE ledger.singleton
        """,
        parameters=(),
    ),
)

ASK_THREE_QUERY_PLAN: tuple[QuerySpec, ...] = (
    ASK_QUERY_SPECS[0],
    ASK_QUERY_SPECS[2],
    ASK_QUERY_SPECS[5],
)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-url",
        default=os.getenv("LEDGER_BENCHMARK_ADMIN_URL", DEFAULT_ADMIN_URL),
        help="administrative PostgreSQL URL used only to create/drop the disposable database",
    )
    parser.add_argument("--transactions", type=int, default=DEFAULT_TRANSACTION_COUNT)
    parser.add_argument(
        "--rebuild-limit-seconds",
        type=float,
        default=DEFAULT_REBUILD_LIMIT_SECONDS,
    )
    parser.add_argument(
        "--read-limit-seconds",
        type=float,
        default=DEFAULT_READ_LIMIT_SECONDS,
    )
    parser.add_argument(
        "--ask-plan-limit-seconds",
        type=float,
        default=DEFAULT_ASK_PLAN_LIMIT_SECONDS,
    )
    parser.add_argument("--read-runs", type=int, default=5)
    parsed = parser.parse_args(arguments)
    if parsed.transactions <= 0:
        parser.error("--transactions must be positive")
    if (
        parsed.rebuild_limit_seconds <= 0
        or parsed.read_limit_seconds <= 0
        or parsed.ask_plan_limit_seconds <= 0
    ):
        parser.error("time limits must be positive")
    if parsed.read_runs <= 0:
        parser.error("--read-runs must be positive")
    return parsed


def disposable_database_url(admin_url: str, database_name: str) -> str:
    if not database_name.startswith(DATABASE_PREFIX):
        raise ValueError("benchmark database name does not have the required safety prefix")
    return make_conninfo(admin_url, dbname=database_name)


def required_int(result: Mapping[str, object], key: str) -> int:
    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"analytics refresh result {key!r} must be an integer")
    return value


def create_database(admin_url: str, database_name: str) -> None:
    if not database_name.startswith(DATABASE_PREFIX):
        raise ValueError("refusing to create a database outside the benchmark prefix")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def drop_database(admin_url: str, database_name: str) -> None:
    if not database_name.startswith(DATABASE_PREFIX):
        raise ValueError("refusing to drop a database outside the benchmark prefix")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
        )


def apply_migrations(database_url: str) -> None:
    migration_paths = sorted((REPOSITORY_ROOT / "db" / "migrations").glob("*.sql"))
    if not migration_paths:
        raise RuntimeError("no migrations found")
    with psycopg.connect(database_url) as connection:
        for migration_path in migration_paths:
            content = migration_path.read_text()
            up_section, separator, _down_section = content.partition("-- migrate:down")
            if not separator:
                raise RuntimeError(f"migration lacks a down marker: {migration_path.name}")
            up_sql = up_section.replace("-- migrate:up", "", 1).strip()
            connection.execute(up_sql)


def seed_transactions(database_url: str, transaction_count: int) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO institution (name) VALUES ('Phase 2 Benchmark Institution');

            INSERT INTO account (institution_id, display_name, kind, native_currency, market_code)
            SELECT institution.id, 'Benchmark Account ' || series.index, 'credit_card',
                   CASE WHEN series.index = 9 THEN 'USD' ELSE 'CAD' END,
                   CASE WHEN series.index % 2 = 0 THEN 'CA' ELSE 'TZ' END
            FROM institution
            CROSS JOIN generate_series(0, 9) AS series(index)
            WHERE institution.name = 'Phase 2 Benchmark Institution';

            INSERT INTO category (name, kind)
            SELECT 'Benchmark Category ' || series.index, 'spend'
            FROM generate_series(0, 19) AS series(index);

            INSERT INTO merchant (canonical_name, normalized_key)
            SELECT 'Benchmark Merchant ' || series.index, 'benchmark-merchant-' || series.index
            FROM generate_series(0, 100) AS series(index);

            INSERT INTO fx_rate (base, quote, as_of, rate, source, fetched_at)
            SELECT
                'USD',
                'CAD',
                series.day::date,
                1.35,
                'phase3-benchmark',
                TIMESTAMPTZ '2026-01-01 00:00:00+00'
            FROM generate_series(
                DATE '2023-01-01',
                DATE '2025-12-31',
                INTERVAL '1 day'
            ) AS series(day);
            """
        )
        connection.execute(
            """
            WITH source AS (
                SELECT
                    series.index,
                    CASE WHEN series.index < 36 THEN 0 ELSE mod(series.index, 10) END
                        AS account_index,
                    CASE WHEN series.index < 36 THEN 0 ELSE mod(series.index, 20) END
                        AS category_index,
                    CASE WHEN series.index < 36 THEN 100 ELSE mod(series.index, 100) END
                        AS merchant_index,
                    CASE
                        WHEN series.index < 36
                            THEN (DATE '2023-01-01' + series.index * INTERVAL '1 month')::date
                        ELSE (DATE '2024-01-01' + mod(series.index, 730))::date
                    END AS booked_date,
                    CASE
                        WHEN series.index < 36 THEN 19.99
                        ELSE 10 + floor(series.index / 100)::numeric / 100
                    END::numeric(14, 2) AS amount
                FROM generate_series(0, %s - 1) AS series(index)
            )
            INSERT INTO txn (
                account_id, booked_date, description_raw,
                merchant_id, category_id,
                amount_native, currency_native,
                amount_base, currency_base, fx_rate, fx_rate_date,
                original_amount, original_currency, fx_fee_amount_native,
                dedup_hash, direction, enrichment
            )
            SELECT
                account.id,
                source.booked_date,
                'Synthetic benchmark purchase ' || source.index,
                merchant.id,
                category.id,
                source.amount,
                CASE WHEN source.account_index = 9 THEN 'USD' ELSE 'CAD' END,
                CASE
                    WHEN mod(source.index, 1000) = 49 THEN NULL
                    WHEN source.account_index = 9 THEN ROUND(source.amount * 1.35, 2)
                    ELSE source.amount
                END,
                'CAD',
                CASE
                    WHEN mod(source.index, 1000) = 49 THEN NULL
                    WHEN source.account_index = 9 THEN 1.35
                    ELSE 1
                END,
                CASE
                    WHEN mod(source.index, 1000) = 49 THEN NULL
                    ELSE source.booked_date
                END,
                CASE
                    WHEN mod(source.index, 1000) = 0
                        THEN ROUND((source.amount - 1.00) / 1.38, 2)
                END,
                CASE WHEN mod(source.index, 1000) = 0 THEN 'USD' END,
                CASE WHEN mod(source.index, 1000) = 0 THEN 1.00 END,
                'phase2-benchmark-' || source.index,
                'debit',
                '{"categorization":{"flow_type":"spend"}}'::jsonb
            FROM source
            JOIN account
              ON account.display_name = 'Benchmark Account ' || source.account_index
            JOIN category
              ON category.name = 'Benchmark Category ' || source.category_index
            JOIN merchant
              ON merchant.normalized_key = 'benchmark-merchant-' || source.merchant_index
            """,
            (transaction_count,),
        )
        row = connection.execute("SELECT count(*) AS count FROM txn").fetchone()
        persisted_count = int(row[0]) if row is not None else 0
        if persisted_count != transaction_count:
            raise AssertionError(
                f"expected {transaction_count} benchmark transactions, found {persisted_count}"
            )
        workload = connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE original_currency = 'USD')::int,
                COUNT(*) FILTER (WHERE amount_base IS NULL)::int
            FROM txn
            """
        ).fetchone()
        if workload is None or int(workload[0]) < 1:
            raise AssertionError("benchmark did not seed FX comparison evidence")
        if transaction_count >= 50 and int(workload[1]) < 1:
            raise AssertionError("benchmark did not seed pending-FX coverage")


def verify_fx_rate_watermark(database_url: str) -> None:
    """Prove the published generation fences and detects later FX-rate writes."""

    with psycopg.connect(database_url) as connection:
        published = connection.execute(
            """
            SELECT run.result ->> 'fx_rate_watermark' AS fx_rate_watermark
            FROM analytics_settings AS settings
            JOIN analytics_run AS run
              ON run.generation = settings.published_generation
            JOIN ledger_settings AS ledger ON ledger.singleton
            WHERE settings.singleton
              AND run.base_currency = ledger.base_currency
              AND run.status = 'succeeded'
            """
        ).fetchone()
        if published is None or not isinstance(published[0], str) or not published[0]:
            raise AssertionError(
                "published analytics run omitted its fx_rate_watermark"
            )

        changed_rate = connection.execute(
            """
            WITH published AS (
                SELECT (run.result ->> 'fx_rate_watermark')::timestamptz AS watermark
                FROM analytics_settings AS settings
                JOIN analytics_run AS run
                  ON run.generation = settings.published_generation
                JOIN ledger_settings AS ledger ON ledger.singleton
                WHERE settings.singleton
                  AND run.base_currency = ledger.base_currency
                  AND run.status = 'succeeded'
            ), target AS (
                SELECT base, quote, as_of
                FROM fx_rate
                ORDER BY as_of DESC, base, quote
                LIMIT 1
            )
            UPDATE fx_rate AS rate
            SET fetched_at = published.watermark + INTERVAL '1 second'
            FROM published, target
            WHERE rate.base = target.base
              AND rate.quote = target.quote
              AND rate.as_of = target.as_of
            RETURNING rate.fetched_at
            """
        ).fetchone()
        if changed_rate is None:
            raise AssertionError("FX watermark test could not update its fixture rate")
        detected = connection.execute(
            """
            WITH published AS (
                SELECT (run.result ->> 'fx_rate_watermark')::timestamptz AS watermark
                FROM analytics_settings AS settings
                JOIN analytics_run AS run
                  ON run.generation = settings.published_generation
                JOIN ledger_settings AS ledger ON ledger.singleton
                WHERE settings.singleton
                  AND run.base_currency = ledger.base_currency
                  AND run.status = 'succeeded'
            )
            SELECT MAX(rate.fetched_at) > published.watermark AS fx_rates_changed
            FROM fx_rate AS rate
            CROSS JOIN published
            GROUP BY published.watermark
            """
        ).fetchone()
        if detected is None or detected[0] is not True:
            raise AssertionError(
                "a post-generation FX-rate write was not detected as newer"
            )
        # The detection probe must not alter the benchmark generation or query corpus.
        connection.rollback()


def measure_warm_reads(
    database_url: str,
    *,
    runs: int,
) -> tuple[ReadMeasurement, ...]:
    measurements: list[ReadMeasurement] = []
    with psycopg.connect(database_url) as connection:
        for name, query in READ_QUERIES:
            connection.execute(query).fetchall()
            samples: list[float] = []
            for _run in range(runs):
                started = perf_counter()
                connection.execute(query).fetchall()
                samples.append((perf_counter() - started) * 1000)
            ordered = sorted(samples)
            measurements.append(
                ReadMeasurement(
                    name=name,
                    runs=runs,
                    minimum_ms=round(ordered[0], 3),
                    median_ms=round(ordered[len(ordered) // 2], 3),
                    maximum_ms=round(ordered[-1], 3),
                )
            )
    return tuple(measurements)


def measurement(name: str, samples: list[float], runs: int) -> ReadMeasurement:
    ordered = sorted(samples)
    return ReadMeasurement(
        name=name,
        runs=runs,
        minimum_ms=round(ordered[0], 3),
        median_ms=round(ordered[len(ordered) // 2], 3),
        maximum_ms=round(ordered[-1], 3),
    )


def execute_read_only_query(
    connection: psycopg.Connection[tuple[object, ...]],
    spec: QuerySpec,
) -> None:
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = connection.execute(spec.query, spec.parameters).fetchall()
        if len(rows) < spec.minimum_rows:
            raise AssertionError(
                f"{spec.name} returned {len(rows)} rows; "
                f"expected at least {spec.minimum_rows}"
            )


def measure_ask_queries(
    database_url: str,
    *,
    runs: int,
) -> tuple[ReadMeasurement, ...]:
    measurements: list[ReadMeasurement] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        for spec in ASK_QUERY_SPECS:
            execute_read_only_query(connection, spec)
            samples: list[float] = []
            for _run in range(runs):
                started = perf_counter()
                execute_read_only_query(connection, spec)
                samples.append((perf_counter() - started) * 1000)
            measurements.append(measurement(spec.name, samples, runs))
    return tuple(measurements)


def execute_ask_plan(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for spec in ASK_THREE_QUERY_PLAN:
            rows = connection.execute(spec.query, spec.parameters).fetchall()
            if len(rows) < spec.minimum_rows:
                raise AssertionError(
                    f"three-query plan member {spec.name} returned too few rows"
                )


def measure_ask_plan(database_url: str, *, runs: int) -> ReadMeasurement:
    with psycopg.connect(database_url, autocommit=True) as connection:
        execute_ask_plan(connection)
        samples: list[float] = []
        for _run in range(runs):
            started = perf_counter()
            execute_ask_plan(connection)
            samples.append((perf_counter() - started) * 1000)
    return measurement("ask_three_query_plan", samples, runs)


def execute_benchmark(arguments: argparse.Namespace) -> BenchmarkResult:
    database_name = f"{DATABASE_PREFIX}{uuid4().hex}"
    database_url = disposable_database_url(arguments.admin_url, database_name)
    create_database(arguments.admin_url, database_name)
    try:
        apply_migrations(database_url)
        seed_transactions(database_url, arguments.transactions)
        service = AnalyticsRefreshService(
            repository=PostgresAnalyticsRepository(database_url),
            today=lambda: date(2026, 1, 1),
        )
        started = perf_counter()
        refresh_result = service.run({"mode": "full"})
        rebuild_seconds = perf_counter() - started
        verify_fx_rate_watermark(database_url)
        warm_reads = measure_warm_reads(database_url, runs=arguments.read_runs)
        ask_warm_queries = measure_ask_queries(database_url, runs=arguments.read_runs)
        ask_three_query_plan = measure_ask_plan(database_url, runs=arguments.read_runs)
        result = BenchmarkResult(
            transaction_count=arguments.transactions,
            rebuild_seconds=round(rebuild_seconds, 3),
            rebuild_limit_seconds=arguments.rebuild_limit_seconds,
            fx_rate_watermark_verified=True,
            aggregate_count=required_int(refresh_result, "aggregate_count"),
            recurring_series_count=required_int(refresh_result, "recurring_series_count"),
            finding_count=required_int(refresh_result, "finding_count"),
            warm_read_limit_seconds=arguments.read_limit_seconds,
            warm_reads=warm_reads,
            ask_warm_query_limit_seconds=arguments.read_limit_seconds,
            ask_warm_queries=ask_warm_queries,
            ask_three_query_plan_limit_seconds=arguments.ask_plan_limit_seconds,
            ask_three_query_plan=ask_three_query_plan,
        )
        if rebuild_seconds >= arguments.rebuild_limit_seconds:
            raise AssertionError(
                f"full analytics rebuild took {rebuild_seconds:.3f}s; "
                f"limit is {arguments.rebuild_limit_seconds:.3f}s"
            )
        failed_reads = [
            measurement
            for measurement in warm_reads
            if measurement.maximum_ms >= arguments.read_limit_seconds * 1000
        ]
        if failed_reads:
            names = ", ".join(measurement.name for measurement in failed_reads)
            raise AssertionError(
                f"warm Insights reads exceeded {arguments.read_limit_seconds:.3f}s: {names}"
            )
        failed_ask_queries = [
            item
            for item in ask_warm_queries
            if item.maximum_ms >= arguments.read_limit_seconds * 1000
        ]
        if failed_ask_queries:
            names = ", ".join(item.name for item in failed_ask_queries)
            raise AssertionError(
                f"warm deterministic Ask queries exceeded "
                f"{arguments.read_limit_seconds:.3f}s: {names}"
            )
        if ask_three_query_plan.maximum_ms >= arguments.ask_plan_limit_seconds * 1000:
            raise AssertionError(
                f"warm three-query Ask plan took {ask_three_query_plan.maximum_ms:.3f}ms; "
                f"limit is {arguments.ask_plan_limit_seconds:.3f}s"
            )
        return result
    finally:
        drop_database(arguments.admin_url, database_name)


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = parse_arguments(arguments)
    result = execute_benchmark(parsed)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
