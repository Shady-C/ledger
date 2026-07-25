"""Run the Phase 2 analytics acceptance benchmark in a disposable database.

Prerequisite: a PostgreSQL 16 + pgvector server matching the development stack.
The default URL targets the local Docker Compose PostgreSQL service. Run with:

    uv run --project services/worker --extra dev \
      python scripts/phase2_analytics_benchmark.py

The script creates a uniquely named ``ledger_benchmark_*`` database, applies
the checked-in migrations, inserts exactly 100,000 synthetic transactions, runs
the production analytics refresh service, warms representative materialized
Insights reads, verifies the Phase 2 time limits, and drops the database even
when an assertion fails.
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
    aggregate_count: int
    recurring_series_count: int
    finding_count: int
    warm_read_limit_seconds: float
    warm_reads: tuple[ReadMeasurement, ...]


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
    parser.add_argument("--read-runs", type=int, default=5)
    parsed = parser.parse_args(arguments)
    if parsed.transactions <= 0:
        parser.error("--transactions must be positive")
    if parsed.rebuild_limit_seconds <= 0 or parsed.read_limit_seconds <= 0:
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
            SELECT institution.id, 'Benchmark Account ' || series.index, 'credit_card', 'CAD',
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
                dedup_hash, direction, enrichment
            )
            SELECT
                account.id,
                source.booked_date,
                'Synthetic benchmark purchase ' || source.index,
                merchant.id,
                category.id,
                source.amount,
                'CAD',
                source.amount,
                'CAD',
                1,
                source.booked_date,
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
        warm_reads = measure_warm_reads(database_url, runs=arguments.read_runs)
        result = BenchmarkResult(
            transaction_count=arguments.transactions,
            rebuild_seconds=round(rebuild_seconds, 3),
            rebuild_limit_seconds=arguments.rebuild_limit_seconds,
            aggregate_count=required_int(refresh_result, "aggregate_count"),
            recurring_series_count=required_int(refresh_result, "recurring_series_count"),
            finding_count=required_int(refresh_result, "finding_count"),
            warm_read_limit_seconds=arguments.read_limit_seconds,
            warm_reads=warm_reads,
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
        return result
    finally:
        drop_database(arguments.admin_url, database_name)


def main(arguments: Sequence[str] | None = None) -> None:
    parsed = parse_arguments(arguments)
    result = execute_benchmark(parsed)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
