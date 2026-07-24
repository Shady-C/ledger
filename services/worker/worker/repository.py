"""PostgreSQL job queue and canonical-ledger persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from worker.ai_categorization import (
    CategoryKind,
    CategoryOption,
    UnresolvedMerchantFlow,
)
from worker.fx import FXRequirement, MissingFXRateError
from worker.models import (
    AccountKind,
    CanonicalTransaction,
    CategorySource,
    FlowType,
    StatementMetadata,
)
from worker.reconcile import ReconciliationResult, StatementPeriod


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    claim_token: str | None = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass(frozen=True, slots=True)
class AccountProfile:
    kind: AccountKind
    native_currency: str


class LeaseLostError(RuntimeError):
    """Raised when a superseded worker tries to mutate a reclaimed job."""


class BaseCurrencyChangedError(RuntimeError):
    """Canonical rows were stamped before a concurrent base-currency switch."""


@dataclass(frozen=True, slots=True)
class PersistResult:
    statement_id: str
    added: int
    skipped: int
    reconcile_status: str
    coverage_gaps: tuple[StatementPeriod, ...] = ()


@dataclass(slots=True)
class MemoryStatement:
    account_id: str
    metadata: StatementMetadata
    period: StatementPeriod
    reconciliation: ReconciliationResult
    status: str


class LedgerRepository(Protocol):
    def get_account_profile(self, account_id: str) -> AccountProfile: ...

    def get_account_kind(self, account_id: str) -> AccountKind: ...

    def get_base_currency(self) -> str: ...

    def load_adapter_mapping(
        self, *, account_id: str, format: str, fingerprint: str
    ) -> dict[str, object] | None: ...

    def save_adapter_mapping(
        self,
        *,
        account_id: str,
        format: str,
        fingerprint: str,
        mapping: dict[str, object],
    ) -> None: ...

    def enqueue_categorization_job(self) -> None: ...

    def enqueue_fx_refresh_job(self, *, target_base_currency: str) -> None: ...

    def persist_statement(
        self,
        *,
        account_id: str,
        source_file_key: str,
        metadata: StatementMetadata,
        rows: tuple[CanonicalTransaction, ...],
        reconciliation: ReconciliationResult,
    ) -> PersistResult: ...


class JobRepository(Protocol):
    def claim_next_job(self, *, timeout_seconds: float) -> Job | None: ...

    def heartbeat_job(self, job: Job) -> None: ...

    def complete_job(self, job: Job, result: dict[str, Any], *, needs_ai: bool) -> None: ...

    def fail_job(
        self,
        job: Job,
        error: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None: ...

    def retry_job(self, job: Job, error: str) -> bool: ...


class PostgresRepository(LedgerRepository, JobRepository):
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be blank")
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def claim_next_job(self, *, timeout_seconds: float) -> Job | None:
        claim_token = uuid4()
        # A lease expiry is a failed attempt just like an explicit provider
        # failure.  Retire exhausted leases before selecting work so a crashed
        # worker cannot make one job reclaimable forever.
        expire_exhausted = """
            UPDATE job
            SET status = 'failed',
                error = 'job lease expired after retry budget was exhausted',
                finished_at = now(), claim_token = NULL, updated_at = now()
            WHERE status = 'claimed'
              AND claimed_at < now() - make_interval(secs => %s)
              AND retry_count >= max_retries
        """
        query = """
            WITH next_job AS (
                SELECT id, status AS previous_status
                FROM job
                WHERE status = 'queued'
                   OR (
                       status = 'claimed'
                       AND claimed_at < now() - make_interval(secs => %s)
                       AND retry_count < max_retries
                   )
                ORDER BY
                    CASE WHEN status = 'queued' THEN 0 ELSE 1 END,
                    created_at,
                    id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE job AS target
            SET status = 'claimed', claim_token = %s, claimed_at = now(),
                retry_count = target.retry_count
                    + CASE WHEN next_job.previous_status = 'claimed' THEN 1 ELSE 0 END,
                payload = target.payload - 'rerun_requested',
                finished_at = NULL, result = NULL, error = NULL, updated_at = now()
            FROM next_job
            WHERE target.id = next_job.id
            RETURNING target.id::text AS id, target.kind, target.payload,
                      target.claim_token::text AS claim_token,
                      target.retry_count, target.max_retries
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(expire_exhausted, (timeout_seconds,))
            cursor.execute(query, (timeout_seconds, claim_token))
            row = cursor.fetchone()
        if row is None:
            return None
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise TypeError("job payload must be a JSON object")
        return Job(
            id=str(row["id"]),
            kind=str(row["kind"]),
            payload=payload,
            claim_token=str(row["claim_token"]),
            retry_count=int(row["retry_count"]),
            max_retries=int(row["max_retries"]),
        )

    def heartbeat_job(self, job: Job) -> None:
        token = _claim_token(job)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE job
                SET claimed_at = now(), updated_at = now()
                WHERE id = %s AND claim_token = %s AND status = 'claimed'
                """,
                (job.id, token),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"lease for job {job.id} is no longer owned")

    def complete_job(self, job: Job, result: dict[str, Any], *, needs_ai: bool) -> None:
        status = "needs_ai" if needs_ai else "done"
        token = _claim_token(job)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE job
                SET status = CASE
                        WHEN kind IN ('categorize', 'fx_refresh')
                         AND payload @> '{"rerun_requested": true}'::jsonb
                        THEN 'queued'
                        ELSE %s
                    END,
                    payload = payload - 'rerun_requested',
                    result = CASE
                        WHEN kind IN ('categorize', 'fx_refresh')
                         AND payload @> '{"rerun_requested": true}'::jsonb
                        THEN NULL
                        ELSE %s
                    END,
                    error = NULL,
                    claimed_at = CASE
                        WHEN kind IN ('categorize', 'fx_refresh')
                         AND payload @> '{"rerun_requested": true}'::jsonb
                        THEN NULL
                        ELSE claimed_at
                    END,
                    finished_at = CASE
                        WHEN kind IN ('categorize', 'fx_refresh')
                         AND payload @> '{"rerun_requested": true}'::jsonb
                        THEN NULL
                        ELSE now()
                    END,
                    claim_token = NULL,
                    updated_at = now()
                WHERE id = %s AND claim_token = %s AND status = 'claimed'
                """,
                (status, Jsonb(result), job.id, token),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"lease for job {job.id} is no longer owned")

    def fail_job(
        self,
        job: Job,
        error: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        token = _claim_token(job)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE job
                SET status = 'failed', result = %s, error = %s,
                    finished_at = now(), claim_token = NULL, updated_at = now()
                WHERE id = %s AND claim_token = %s AND status = 'claimed'
                """,
                (Jsonb(result) if result is not None else None, error[:500], job.id, token),
            )
            if cursor.rowcount != 1:
                raise LeaseLostError(f"lease for job {job.id} is no longer owned")

    def retry_job(self, job: Job, error: str) -> bool:
        token = _claim_token(job)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE job
                SET status = CASE
                        WHEN retry_count < max_retries THEN 'queued'
                        ELSE 'failed'
                    END,
                    retry_count = CASE
                        WHEN retry_count < max_retries THEN retry_count + 1
                        ELSE retry_count
                    END,
                    claimed_at = CASE
                        WHEN retry_count < max_retries THEN NULL
                        ELSE claimed_at
                    END,
                    finished_at = CASE
                        WHEN retry_count < max_retries THEN NULL
                        ELSE now()
                    END,
                    payload = payload - 'rerun_requested',
                    claim_token = NULL,
                    error = %s,
                    updated_at = now()
                WHERE id = %s AND claim_token = %s AND status = 'claimed'
                RETURNING status
                """,
                (error[:500], job.id, token),
            )
            row = cursor.fetchone()
            if row is None:
                raise LeaseLostError(f"lease for job {job.id} is no longer owned")
        return str(row["status"]) == "queued"

    def get_account_kind(self, account_id: str) -> AccountKind:
        return self.get_account_profile(account_id).kind

    def get_account_profile(self, account_id: str) -> AccountProfile:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT kind, native_currency FROM account WHERE id = %s", (account_id,))
            row = cursor.fetchone()
        if row is None:
            raise ValueError("account does not exist")
        return AccountProfile(
            kind=AccountKind(str(row["kind"])), native_currency=str(row["native_currency"])
        )

    def get_base_currency(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT base_currency FROM ledger_settings WHERE singleton"
            ).fetchone()
        if row is None:
            raise RuntimeError("ledger settings are not initialized")
        return str(row["base_currency"])

    def load_adapter_mapping(
        self, *, account_id: str, format: str, fingerprint: str
    ) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT candidate.column_map
                FROM account
                JOIN LATERAL (
                    SELECT column_map
                    FROM adapter
                    WHERE institution_id IS NOT DISTINCT FROM account.institution_id
                      AND format = %s
                      AND detection_fingerprint ->> 'hash' = %s
                      AND column_map IS NOT NULL
                    ORDER BY version DESC
                    LIMIT 1
                ) AS candidate ON true
                WHERE account.id = %s
                """,
                (format, fingerprint, account_id),
            ).fetchone()
        if row is None or not isinstance(row["column_map"], dict):
            return None
        return dict(row["column_map"])

    def save_adapter_mapping(
        self,
        *,
        account_id: str,
        format: str,
        fingerprint: str,
        mapping: dict[str, object],
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT institution_id::text AS institution_id FROM account WHERE id = %s",
                (account_id,),
            )
            account = cursor.fetchone()
            if account is None:
                raise ValueError("account does not exist")
            institution_id = account["institution_id"]
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"adapter:{institution_id}:{format}",),
            )
            cursor.execute(
                """
                SELECT column_map
                FROM adapter
                WHERE institution_id IS NOT DISTINCT FROM %s
                  AND format = %s
                  AND detection_fingerprint ->> 'hash' = %s
                ORDER BY version DESC
                LIMIT 1
                """,
                (institution_id, format, fingerprint),
            )
            if cursor.fetchone() is not None:
                return
            cursor.execute(
                """
                INSERT INTO adapter (
                    institution_id, format, column_map, detection_fingerprint, version
                )
                SELECT %s, %s, %s, %s,
                       COALESCE(max(version), 0) + 1
                FROM adapter
                WHERE institution_id IS NOT DISTINCT FROM %s AND format = %s
                """,
                (
                    institution_id,
                    format,
                    Jsonb(mapping),
                    Jsonb({"hash": fingerprint}),
                    institution_id,
                    format,
                ),
            )

    def list_active_categories(self) -> tuple[CategoryOption, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id::text AS id, name, kind
                FROM category
                WHERE archived_at IS NULL
                ORDER BY parent_id NULLS FIRST, lower(name), id
                """
            ).fetchall()
        return tuple(
            CategoryOption(id=str(row["id"]), name=str(row["name"]), kind=row["kind"])
            for row in rows
        )

    def list_unresolved_merchant_flows(self, *, limit: int) -> tuple[UnresolvedMerchantFlow, ...]:
        if limit <= 0:
            raise ValueError("unresolved merchant limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH unresolved AS (
                    SELECT DISTINCT
                        merchant.id AS merchant_id,
                        merchant.normalized_key AS merchant_key,
                        COALESCE(
                            NULLIF(txn.enrichment #>> '{categorization,flow_type}', ''),
                            CASE
                                WHEN txn.direction IN ('fee', 'interest') THEN 'fee'
                                WHEN txn.direction = 'refund' THEN 'refund'
                                WHEN txn.direction = 'payment' THEN 'transfer'
                                WHEN account.kind <> 'credit_card'
                                  AND txn.direction = 'credit' THEN 'income'
                                WHEN account.kind = 'credit_card'
                                  AND txn.amount_native < 0 THEN 'refund'
                                ELSE 'spend'
                            END
                        ) AS flow_type
                    FROM txn
                    JOIN merchant ON merchant.id = txn.merchant_id
                    JOIN account ON account.id = txn.account_id
                    WHERE txn.category_source = 'fallback'
                )
                SELECT unresolved.merchant_id::text AS merchant_id,
                       unresolved.merchant_key,
                       unresolved.flow_type
                FROM unresolved
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM merchant_category_mapping AS mapping
                    JOIN category AS mapped_category
                      ON mapped_category.id = mapping.category_id
                    WHERE mapping.merchant_id = unresolved.merchant_id
                      AND mapping.flow_type = unresolved.flow_type
                      AND mapped_category.archived_at IS NULL
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM categorization_proposal AS proposal
                    WHERE proposal.merchant_id = unresolved.merchant_id
                      AND proposal.flow_type = unresolved.flow_type
                )
                ORDER BY unresolved.merchant_id, unresolved.flow_type
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(
            UnresolvedMerchantFlow(
                merchant_id=str(row["merchant_id"]),
                merchant_key=str(row["merchant_key"]),
                flow_type=FlowType(str(row["flow_type"])),
            )
            for row in rows
        )

    def apply_ai_category(
        self,
        *,
        merchant_id: str,
        flow_type: FlowType,
        category_id: str,
        confidence: float,
    ) -> int:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM merchant_category_mapping AS mapping
                USING category
                WHERE mapping.merchant_id = %s
                  AND mapping.flow_type = %s
                  AND mapping.source = 'ai'
                  AND category.id = mapping.category_id
                  AND category.archived_at IS NOT NULL
                """,
                (merchant_id, flow_type.value),
            )
            cursor.execute(
                """
                INSERT INTO merchant_category_mapping (
                    merchant_id, flow_type, category_id, source, confidence
                ) VALUES (%s, %s, %s, 'ai', %s)
                ON CONFLICT (merchant_id, flow_type) DO NOTHING
                RETURNING id
                """,
                (merchant_id, flow_type.value, category_id, confidence),
            )
            if cursor.fetchone() is None:
                # A concurrent user-level learned mapping takes precedence.
                return 0
            cursor.execute(
                """
                UPDATE txn
                SET category_id = %s,
                    category_source = 'ai',
                    category_confidence = %s,
                    updated_at = now()
                FROM account
                WHERE txn.account_id = account.id
                  AND txn.merchant_id = %s
                  AND txn.category_source = 'fallback'
                  AND COALESCE(
                        NULLIF(txn.enrichment #>> '{categorization,flow_type}', ''),
                        CASE
                            WHEN txn.direction IN ('fee', 'interest') THEN 'fee'
                            WHEN txn.direction = 'refund' THEN 'refund'
                            WHEN txn.direction = 'payment' THEN 'transfer'
                            WHEN account.kind <> 'credit_card'
                              AND txn.direction = 'credit' THEN 'income'
                            WHEN account.kind = 'credit_card'
                              AND txn.amount_native < 0 THEN 'refund'
                            ELSE 'spend'
                        END
                      ) = %s
                """,
                (category_id, confidence, merchant_id, flow_type.value),
            )
            return cursor.rowcount

    def record_categorization_proposal(
        self,
        *,
        opaque_key: UUID,
        merchant_id: str,
        flow_type: FlowType,
        proposed_category_id: str | None,
        proposed_category_name: str | None,
        proposed_category_kind: CategoryKind | None,
        confidence: float,
        provider: str,
        model: str,
        raw_assignment: dict[str, object],
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                INSERT INTO categorization_proposal (
                    opaque_key, merchant_id, flow_type, proposed_category_id,
                    proposed_category_name, proposed_category_kind, confidence,
                    provider, model, raw_assignment
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (merchant_id, flow_type) WHERE status = 'pending'
                DO NOTHING
                RETURNING id
                """,
                (
                    opaque_key,
                    merchant_id,
                    flow_type.value,
                    proposed_category_id,
                    proposed_category_name,
                    proposed_category_kind,
                    confidence,
                    provider,
                    model,
                    Jsonb(raw_assignment),
                ),
            ).fetchone()
        return row is not None

    def enqueue_categorization_job(self) -> None:
        self._enqueue_followup_job(
            kind="categorize",
            payload={},
            deduplication_key="unresolved-merchants",
            match_payload=None,
        )

    def enqueue_fx_refresh_job(self, *, target_base_currency: str) -> None:
        target = _currency_code(target_base_currency)
        payload: dict[str, object] = {"target_base_currency": target}
        self._enqueue_followup_job(
            kind="fx_refresh",
            payload=payload,
            deduplication_key=f"fx-refresh:{target}",
            match_payload=payload,
        )

    def _enqueue_followup_job(
        self,
        *,
        kind: str,
        payload: dict[str, object],
        deduplication_key: str,
        match_payload: dict[str, object] | None,
    ) -> None:
        """Coalesce work without losing an enqueue racing a claimed scan."""

        payload_filter = "" if match_payload is None else "AND payload @> %s"
        update_parameters: tuple[object, ...] = (
            (kind,) if match_payload is None else (kind, Jsonb(match_payload))
        )
        update = f"""
            UPDATE job
            SET payload = payload || '{{"rerun_requested": true}}'::jsonb,
                updated_at = now()
            WHERE kind = %s
              AND status IN ('queued', 'claimed')
              {payload_filter}
            RETURNING id
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(update, update_parameters)
            if cursor.fetchone() is not None:
                return
            cursor.execute(
                """
                INSERT INTO job (kind, payload, deduplication_key)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (kind, Jsonb(payload), deduplication_key),
            )
            if cursor.fetchone() is not None:
                return
            # A concurrent insert won the partial unique-index race. Mark that
            # active job so an enqueue after its scan still forces one rerun.
            cursor.execute(update, update_parameters)
            if cursor.fetchone() is None:
                raise RuntimeError(f"could not enqueue or coalesce {kind} job")

    def list_fx_requirements(self, *, target_currency: str) -> tuple[FXRequirement, ...]:
        target = _currency_code(target_currency)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT currency_native AS base, %s AS quote, booked_date AS as_of
                FROM txn
                WHERE currency_native <> %s
                UNION
                SELECT DISTINCT currency AS base, %s AS quote, period_start AS as_of
                FROM statement
                WHERE currency <> %s AND opening_balance IS NOT NULL
                UNION
                SELECT DISTINCT currency AS base, %s AS quote, period_end AS as_of
                FROM statement
                WHERE currency <> %s AND closing_balance IS NOT NULL
                UNION
                SELECT DISTINCT native_currency AS base, %s AS quote, CURRENT_DATE AS as_of
                FROM account
                WHERE native_currency <> %s
                UNION
                SELECT DISTINCT
                    upper(enrichment #>> '{foreign_spend,currency}') AS base,
                    currency_native AS quote,
                    booked_date AS as_of
                FROM txn
                WHERE upper(enrichment #>> '{foreign_spend,currency}') ~ '^[A-Z]{3}$'
                  AND (enrichment #>> '{foreign_spend,amount}')
                        ~ '^-?[0-9]+([.][0-9]+)?$'
                  AND upper(enrichment #>> '{foreign_spend,currency}') <> currency_native
                ORDER BY base, as_of
                """,
                (target, target, target, target, target, target, target, target),
            ).fetchall()
        return tuple(
            FXRequirement(base=str(row["base"]), quote=str(row["quote"]), as_of=row["as_of"])
            for row in rows
        )

    def rebuild_base_currency(self, *, target_currency: str, max_staleness_days: int) -> int:
        target = _currency_code(target_currency)
        if not 0 <= max_staleness_days <= 7:
            raise ValueError("max_staleness_days must be between 0 and 7")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('ledger-base-currency'))")
            cursor.execute(
                """
                WITH requirement AS (
                    SELECT DISTINCT
                        currency_native AS base, %s::text AS quote, booked_date AS as_of
                    FROM txn
                    WHERE currency_native <> %s
                    UNION
                    SELECT DISTINCT
                        currency AS base, %s::text AS quote, period_start AS as_of
                    FROM statement
                    WHERE currency <> %s AND opening_balance IS NOT NULL
                    UNION
                    SELECT DISTINCT
                        currency AS base, %s::text AS quote, period_end AS as_of
                    FROM statement
                    WHERE currency <> %s AND closing_balance IS NOT NULL
                    UNION
                    SELECT DISTINCT
                        native_currency AS base, %s::text AS quote, CURRENT_DATE AS as_of
                    FROM account
                    WHERE native_currency <> %s
                    UNION
                    SELECT DISTINCT
                        upper(enrichment #>> '{foreign_spend,currency}') AS base,
                        currency_native AS quote,
                        booked_date AS as_of
                    FROM txn
                    WHERE upper(enrichment #>> '{foreign_spend,currency}') ~ '^[A-Z]{3}$'
                      AND (enrichment #>> '{foreign_spend,amount}')
                            ~ '^-?[0-9]+([.][0-9]+)?$'
                      AND upper(enrichment #>> '{foreign_spend,currency}')
                            <> currency_native
                )
                SELECT count(*) AS missing
                FROM requirement
                WHERE NOT EXISTS (
                      SELECT 1
                      FROM fx_rate
                      WHERE fx_rate.base = requirement.base
                        AND fx_rate.quote = requirement.quote
                        AND as_of BETWEEN
                            requirement.as_of - make_interval(days => %s)
                            AND requirement.as_of
                  )
                """,
                (
                    target,
                    target,
                    target,
                    target,
                    target,
                    target,
                    target,
                    target,
                    max_staleness_days,
                ),
            )
            missing = cursor.fetchone()
            if missing is None or int(missing["missing"]) > 0:
                raise MissingFXRateError("base-currency rebuild is missing one or more rates")
            cursor.execute(
                """
                WITH valuation AS (
                    SELECT
                        txn.id,
                        COALESCE(rate.rate, 1::numeric) AS rate,
                        COALESCE(rate.as_of, txn.booked_date) AS rate_date,
                        COALESCE(rate.source, 'identity') AS source
                    FROM txn
                    LEFT JOIN LATERAL (
                        SELECT fx_rate.rate, fx_rate.as_of, fx_rate.source
                        FROM fx_rate
                        WHERE fx_rate.base = txn.currency_native
                          AND fx_rate.quote = %s
                          AND fx_rate.as_of BETWEEN
                              txn.booked_date - make_interval(days => %s)
                              AND txn.booked_date
                        ORDER BY fx_rate.as_of DESC
                        LIMIT 1
                    ) AS rate ON txn.currency_native <> %s
                )
                UPDATE txn
                SET amount_base = round(txn.amount_native * valuation.rate, 2),
                    currency_base = %s,
                    fx_rate = valuation.rate,
                    fx_rate_date = valuation.rate_date,
                    enrichment = jsonb_set(
                        txn.enrichment,
                        '{fx_source}',
                        to_jsonb(valuation.source::text),
                        true
                    ),
                    updated_at = now()
                FROM valuation
                WHERE txn.id = valuation.id
                """,
                (target, max_staleness_days, target, target),
            )
            rebuilt = cursor.rowcount
            cursor.execute(
                """
                UPDATE ledger_settings
                SET base_currency = %s, updated_at = now()
                WHERE singleton
                """,
                (target,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("ledger settings are not initialized")
        return rebuilt

    def persist_statement(
        self,
        *,
        account_id: str,
        source_file_key: str,
        metadata: StatementMetadata,
        rows: tuple[CanonicalTransaction, ...],
        reconciliation: ReconciliationResult,
    ) -> PersistResult:
        if metadata.period_start is None or metadata.period_end is None:
            raise ValueError("statement period is required for persistence")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('ledger-base-currency'))")
            cursor.execute("SELECT base_currency FROM ledger_settings WHERE singleton FOR SHARE")
            settings = cursor.fetchone()
            if settings is None:
                raise RuntimeError("ledger settings are not initialized")
            current_base = str(settings["base_currency"])
            if any(row.currency_base != current_base for row in rows):
                raise BaseCurrencyChangedError(
                    "base currency changed while statement rows were being prepared"
                )
            self._sync_account_reference(
                cursor,
                account_id=account_id,
                discovered=metadata.account_ref_masked,
            )
            statement_id, arithmetic_status = self._get_or_create_statement(
                cursor,
                account_id=account_id,
                source_file_key=source_file_key,
                metadata=metadata,
                reconcile_status=reconciliation.status,
            )
            added = 0
            for row in rows:
                if self._existing_ofx_transaction_matches(cursor, account_id=account_id, row=row):
                    continue
                merchant_id = self._merchant_id(cursor, row.merchant_name, row.merchant_key)
                flow_type = _canonical_flow_type(row)
                learned = self._learned_category(
                    cursor,
                    merchant_id=merchant_id,
                    flow_type=flow_type,
                    deterministic_source=row.category_source.value,
                )
                if learned is None:
                    category_id, deterministic_match = self._category_id(
                        cursor, row.category_name, row.category_kind
                    )
                    category_source = (
                        row.category_source.value if deterministic_match else "fallback"
                    )
                    category_confidence: float | None = (
                        row.category_confidence if deterministic_match else 0.0
                    )
                else:
                    category_id, category_source, category_confidence = learned
                cursor.execute(
                    """
                    INSERT INTO txn (
                        account_id, statement_id, booked_date, posted_date,
                        description_raw, merchant_id, category_id,
                        amount_native, currency_native, amount_base, currency_base,
                        fx_rate, fx_rate_date, external_ref, dedup_hash, direction,
                        enrichment, category_source, category_confidence
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (dedup_hash) DO NOTHING
                    RETURNING id
                    """,
                    (
                        account_id,
                        statement_id,
                        row.booked_date,
                        row.posted_date,
                        row.description_raw,
                        merchant_id,
                        category_id,
                        row.amount_native,
                        row.currency_native,
                        row.amount_base,
                        row.currency_base,
                        row.fx_rate,
                        row.fx_rate_date,
                        row.external_ref,
                        row.dedup_hash,
                        row.direction.value,
                        Jsonb(row.enrichment),
                        category_source,
                        category_confidence,
                    ),
                )
                if cursor.fetchone() is not None:
                    added += 1
                else:
                    self._refresh_transaction_metadata(cursor, row=row)
            reconcile_status, gaps = self._refresh_coverage(
                cursor,
                account_id=account_id,
                current_statement_id=statement_id,
                current_arithmetic_status=arithmetic_status,
            )
        return PersistResult(
            statement_id=statement_id,
            added=added,
            skipped=len(rows) - added,
            reconcile_status=reconcile_status,
            coverage_gaps=gaps,
        )

    @staticmethod
    def _get_or_create_statement(
        cursor: psycopg.Cursor[Any],
        *,
        account_id: str,
        source_file_key: str,
        metadata: StatementMetadata,
        reconcile_status: str,
    ) -> tuple[str, str]:
        cursor.execute(
            """
            INSERT INTO statement (
                account_id, period_start, period_end, opening_balance,
                closing_balance, currency, source_file_key, reconcile_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, source_file_key) DO UPDATE
            SET period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                opening_balance = CASE
                    WHEN EXCLUDED.opening_balance IS NULL
                      OR EXCLUDED.closing_balance IS NULL
                    THEN statement.opening_balance
                    ELSE EXCLUDED.opening_balance
                END,
                closing_balance = CASE
                    WHEN EXCLUDED.opening_balance IS NULL
                      OR EXCLUDED.closing_balance IS NULL
                    THEN statement.closing_balance
                    ELSE EXCLUDED.closing_balance
                END,
                currency = EXCLUDED.currency,
                reconcile_status = CASE
                    WHEN EXCLUDED.opening_balance IS NULL
                      OR EXCLUDED.closing_balance IS NULL
                    THEN statement.reconcile_status
                    ELSE EXCLUDED.reconcile_status
                END,
                updated_at = now()
            RETURNING id::text AS id, reconcile_status
            """,
            (
                account_id,
                metadata.period_start,
                metadata.period_end,
                metadata.opening_balance,
                metadata.closing_balance,
                metadata.currency,
                source_file_key,
                reconcile_status,
            ),
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("statement insert did not return an id")
        return str(created["id"]), str(created["reconcile_status"])

    @staticmethod
    def _sync_account_reference(
        cursor: psycopg.Cursor[Any],
        *,
        account_id: str,
        discovered: str | None,
    ) -> None:
        if discovered is None:
            return
        cursor.execute(
            "SELECT account_ref_masked FROM account WHERE id = %s FOR UPDATE",
            (account_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("account does not exist")
        raw_current = row["account_ref_masked"]
        current = str(raw_current) if raw_current is not None else None
        resolved = _resolve_account_reference(current, discovered)
        if resolved != current:
            cursor.execute(
                "UPDATE account SET account_ref_masked = %s, updated_at = now() WHERE id = %s",
                (resolved, account_id),
            )

    @staticmethod
    def _refresh_transaction_metadata(
        cursor: psycopg.Cursor[Any],
        *,
        row: CanonicalTransaction,
    ) -> None:
        """Fill parser metadata omitted by an older import without changing money truth."""

        if row.posted_date is None:
            return
        cursor.execute(
            "SELECT posted_date FROM txn WHERE dedup_hash = %s FOR UPDATE",
            (row.dedup_hash,),
        )
        existing = cursor.fetchone()
        if existing is None:
            raise RuntimeError("conflicting transaction disappeared during metadata refresh")
        posted_date = existing["posted_date"]
        if posted_date is not None and posted_date != row.posted_date:
            raise ValueError("statement processed date conflicts with an existing transaction")
        if posted_date is None:
            cursor.execute(
                "UPDATE txn SET posted_date = %s, updated_at = now() WHERE dedup_hash = %s",
                (row.posted_date, row.dedup_hash),
            )

    @staticmethod
    def _existing_ofx_transaction_matches(
        cursor: psycopg.Cursor[Any],
        *,
        account_id: str,
        row: CanonicalTransaction,
    ) -> bool:
        if row.external_ref is None or "ofx_transaction_type" not in row.enrichment:
            return False
        cursor.execute(
            """
            SELECT booked_date, amount_native, currency_native
            FROM txn
            WHERE account_id = %s
              AND external_ref = %s
              AND enrichment ? 'ofx_transaction_type'
            FOR UPDATE
            """,
            (account_id, row.external_ref),
        )
        existing = cursor.fetchone()
        if existing is None:
            return False
        if (
            existing["booked_date"] != row.booked_date
            or existing["amount_native"] != row.amount_native
            or str(existing["currency_native"]) != row.currency_native
        ):
            raise ValueError("OFX FITID conflicts with an existing transaction")
        return True

    @staticmethod
    def _category_id(cursor: psycopg.Cursor[Any], name: str, kind: str) -> tuple[str, bool]:
        """Resolve an active deterministic category without mutating taxonomy."""

        cursor.execute(
            """
            SELECT id::text AS id
            FROM category
            WHERE parent_id IS NULL
              AND lower(name) = lower(%s)
              AND kind = %s
              AND archived_at IS NULL
            """,
            (name, kind),
        )
        if row := cursor.fetchone():
            return str(row["id"]), True
        cursor.execute(
            """
            SELECT id::text AS id
            FROM category
            WHERE parent_id IS NULL
              AND lower(name) = 'other'
              AND is_protected
              AND archived_at IS NULL
            """
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("protected Other category is unavailable")
        return str(row["id"]), False

    @staticmethod
    def _learned_category(
        cursor: psycopg.Cursor[Any],
        *,
        merchant_id: str,
        flow_type: FlowType,
        deterministic_source: str,
    ) -> tuple[str, str, float | None] | None:
        cursor.execute(
            """
            SELECT mapping.category_id::text AS category_id,
                   mapping.source,
                   mapping.confidence
            FROM merchant_category_mapping AS mapping
            JOIN category ON category.id = mapping.category_id
            WHERE mapping.merchant_id = %s
              AND mapping.flow_type = %s
              AND category.archived_at IS NULL
              AND category.kind = %s
              AND (
                  mapping.source = 'user_merchant'
                  OR (mapping.source = 'ai' AND %s = 'fallback')
              )
            LIMIT 1
            """,
            (
                merchant_id,
                flow_type.value,
                _category_kind_for_flow(flow_type),
                deterministic_source,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        confidence = row["confidence"]
        return (
            str(row["category_id"]),
            str(row["source"]),
            float(confidence) if confidence is not None else None,
        )

    @staticmethod
    def _merchant_id(cursor: psycopg.Cursor[Any], name: str, key: str) -> str:
        cursor.execute(
            """
            INSERT INTO merchant (canonical_name, normalized_key)
            VALUES (%s, %s)
            ON CONFLICT (normalized_key) DO UPDATE
            SET updated_at = merchant.updated_at
            RETURNING id::text AS id
            """,
            (name, key),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("merchant upsert did not return an id")
        return str(row["id"])

    @staticmethod
    def _refresh_coverage(
        cursor: psycopg.Cursor[Any],
        *,
        account_id: str,
        current_statement_id: str,
        current_arithmetic_status: str,
    ) -> tuple[str, tuple[StatementPeriod, ...]]:
        """Re-evaluate the whole account so out-of-order uploads can close old gaps."""

        cursor.execute(
            """
            SELECT id::text AS id, period_start, period_end, reconcile_status
            FROM statement
            WHERE account_id = %s
            ORDER BY period_start, period_end, id
            """,
            (account_id,),
        )
        statement_rows = cursor.fetchall()
        records = [
            (
                str(row["id"]),
                StatementPeriod(row["period_start"], row["period_end"]),
                (
                    current_arithmetic_status
                    if str(row["id"]) == current_statement_id
                    else str(row["reconcile_status"])
                ),
            )
            for row in statement_rows
        ]
        statuses, gaps = _account_coverage_statuses(records)
        for statement_id, status in statuses.items():
            cursor.execute(
                """
                UPDATE statement
                SET reconcile_status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, statement_id),
            )
        return statuses[current_statement_id], gaps


class InMemoryRepository(LedgerRepository, JobRepository):
    """Behavioral test double that retains production idempotency semantics."""

    def __init__(
        self,
        jobs: list[Job] | None = None,
        *,
        account_kinds: dict[str, AccountKind] | None = None,
        account_currencies: dict[str, str] | None = None,
        account_refs: dict[str, str | None] | None = None,
        default_account_kind: AccountKind = AccountKind.CREDIT_CARD,
        base_currency: str = "CAD",
    ) -> None:
        self.jobs = list(jobs or [])
        self.claimed: list[str] = []
        self.completed: dict[str, dict[str, Any]] = {}
        self.failed: dict[str, str] = {}
        self.transactions: dict[str, CanonicalTransaction] = {}
        self.transaction_accounts: dict[str, str] = {}
        self.statements: dict[str, MemoryStatement] = {}
        self.account_kinds = dict(account_kinds or {})
        self.account_currencies = dict(account_currencies or {})
        self.account_refs = dict(account_refs or {})
        self.default_account_kind = default_account_kind
        self.base_currency = base_currency
        self.adapter_mappings: dict[tuple[str, str, str], dict[str, object]] = {}
        self.categories: list[CategoryOption] = []
        self.unresolved_merchant_flows: list[UnresolvedMerchantFlow] = []
        self.ai_mappings: dict[tuple[str, FlowType], tuple[str, float]] = {}
        self.merchant_category_mappings: dict[
            tuple[str, FlowType], tuple[CategoryOption, CategorySource, float | None]
        ] = {}
        self.categorization_proposals: dict[UUID, dict[str, object]] = {}
        self.retry_events: list[str] = []
        self.heartbeat_count = 0
        self._inflight: dict[str, tuple[Job, datetime]] = {}

    def claim_next_job(self, *, timeout_seconds: float) -> Job | None:
        while True:
            now = datetime.now(UTC)
            if self.jobs:
                candidate = self.jobs.pop(0)
            else:
                stale = sorted(
                    (
                        (claimed_at, job)
                        for job, claimed_at in self._inflight.values()
                        if claimed_at < now - timedelta(seconds=timeout_seconds)
                    ),
                    key=lambda item: item[0],
                )
                if not stale:
                    return None
                candidate = stale[0][1]
                if candidate.retry_count >= candidate.max_retries:
                    self.failed[candidate.id] = "job lease expired after retry budget was exhausted"
                    del self._inflight[candidate.id]
                    continue
                candidate = replace(candidate, retry_count=candidate.retry_count + 1)
            payload = dict(candidate.payload)
            payload.pop("rerun_requested", None)
            job = replace(candidate, payload=payload, claim_token=str(uuid4()))
            self._inflight[job.id] = (job, now)
            self.claimed.append(job.id)
            return job

    def heartbeat_job(self, job: Job) -> None:
        self._assert_lease(job)
        active = self._inflight[job.id][0]
        self._inflight[job.id] = (active, datetime.now(UTC))
        self.heartbeat_count += 1

    def complete_job(self, job: Job, result: dict[str, Any], *, needs_ai: bool) -> None:
        self._assert_lease(job)
        active = self._inflight[job.id][0]
        if (
            active.kind in {"categorize", "fx_refresh"}
            and active.payload.get("rerun_requested") is True
        ):
            payload = dict(active.payload)
            payload.pop("rerun_requested", None)
            self.jobs.append(replace(active, payload=payload, claim_token=None))
            del self._inflight[job.id]
            return
        self.completed[job.id] = {**result, "status": "needs_ai" if needs_ai else "done"}
        del self._inflight[job.id]

    def fail_job(
        self,
        job: Job,
        error: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        self._assert_lease(job)
        self.failed[job.id] = error
        if result is not None:
            self.completed[job.id] = {**result, "status": "failed"}
        del self._inflight[job.id]

    def retry_job(self, job: Job, error: str) -> bool:
        self._assert_lease(job)
        active = self._inflight[job.id][0]
        del self._inflight[job.id]
        self.retry_events.append(job.id)
        if active.retry_count < active.max_retries:
            payload = dict(active.payload)
            payload.pop("rerun_requested", None)
            self.jobs.append(
                replace(
                    active,
                    payload=payload,
                    claim_token=None,
                    retry_count=active.retry_count + 1,
                )
            )
            return True
        self.failed[job.id] = error
        return False

    def get_account_kind(self, account_id: str) -> AccountKind:
        return self.account_kinds.get(account_id, self.default_account_kind)

    def get_account_profile(self, account_id: str) -> AccountProfile:
        return AccountProfile(
            kind=self.get_account_kind(account_id),
            native_currency=self.account_currencies.get(account_id, "CAD"),
        )

    def get_base_currency(self) -> str:
        return self.base_currency

    def load_adapter_mapping(
        self, *, account_id: str, format: str, fingerprint: str
    ) -> dict[str, object] | None:
        value = self.adapter_mappings.get((account_id, format, fingerprint))
        return dict(value) if value is not None else None

    def save_adapter_mapping(
        self,
        *,
        account_id: str,
        format: str,
        fingerprint: str,
        mapping: dict[str, object],
    ) -> None:
        self.adapter_mappings.setdefault((account_id, format, fingerprint), dict(mapping))

    def list_active_categories(self) -> tuple[CategoryOption, ...]:
        return tuple(self.categories)

    def list_unresolved_merchant_flows(self, *, limit: int) -> tuple[UnresolvedMerchantFlow, ...]:
        return tuple(
            item
            for item in self.unresolved_merchant_flows
            if (item.merchant_id, item.flow_type) not in self.ai_mappings
            and item.opaque_key not in self.categorization_proposals
        )[:limit]

    def apply_ai_category(
        self,
        *,
        merchant_id: str,
        flow_type: FlowType,
        category_id: str,
        confidence: float,
    ) -> int:
        key = (merchant_id, flow_type)
        if key in self.ai_mappings:
            return 0
        self.ai_mappings[key] = (category_id, confidence)
        merchant = next(
            (
                item
                for item in self.unresolved_merchant_flows
                if item.merchant_id == merchant_id and item.flow_type is flow_type
            ),
            None,
        )
        category = next((item for item in self.categories if item.id == category_id), None)
        if merchant is not None and category is not None:
            self.merchant_category_mappings[(merchant.merchant_key, flow_type)] = (
                category,
                CategorySource.AI,
                confidence,
            )
        return 1

    def record_categorization_proposal(
        self,
        *,
        opaque_key: UUID,
        merchant_id: str,
        flow_type: FlowType,
        proposed_category_id: str | None,
        proposed_category_name: str | None,
        proposed_category_kind: CategoryKind | None,
        confidence: float,
        provider: str,
        model: str,
        raw_assignment: dict[str, object],
    ) -> bool:
        if opaque_key in self.categorization_proposals:
            return False
        self.categorization_proposals[opaque_key] = {
            "merchant_id": merchant_id,
            "flow_type": flow_type.value,
            "proposed_category_id": proposed_category_id,
            "proposed_category_name": proposed_category_name,
            "proposed_category_kind": proposed_category_kind,
            "confidence": confidence,
            "provider": provider,
            "model": model,
            "raw_assignment": raw_assignment,
        }
        return True

    def enqueue_categorization_job(self) -> None:
        if self._request_active_rerun(kind="categorize", match_payload=None):
            return
        self.jobs.append(Job(id=f"categorize-{uuid4()}", kind="categorize", payload={}))

    def enqueue_fx_refresh_job(self, *, target_base_currency: str) -> None:
        target = _currency_code(target_base_currency)
        payload: dict[str, object] = {"target_base_currency": target}
        if self._request_active_rerun(kind="fx_refresh", match_payload=payload):
            return
        self.jobs.append(
            Job(
                id=f"fx-refresh-{uuid4()}",
                kind="fx_refresh",
                payload={"target_base_currency": target},
            )
        )

    def _request_active_rerun(self, *, kind: str, match_payload: dict[str, object] | None) -> bool:
        def matches(job: Job) -> bool:
            return job.kind == kind and (
                match_payload is None
                or all(job.payload.get(key) == value for key, value in match_payload.items())
            )

        for index, queued in enumerate(self.jobs):
            if matches(queued):
                payload = {**queued.payload, "rerun_requested": True}
                self.jobs[index] = replace(queued, payload=payload)
                return True
        for job_id, (claimed, claimed_at) in tuple(self._inflight.items()):
            if matches(claimed):
                payload = {**claimed.payload, "rerun_requested": True}
                self._inflight[job_id] = (replace(claimed, payload=payload), claimed_at)
                return True
        return False

    def list_fx_requirements(self, *, target_currency: str) -> tuple[FXRequirement, ...]:
        requirements = {
            FXRequirement(row.currency_native, target_currency, row.booked_date)
            for row in self.transactions.values()
            if row.currency_native != target_currency
        }
        for statement in self.statements.values():
            if statement.metadata.currency == target_currency:
                continue
            if statement.metadata.opening_balance is not None:
                requirements.add(
                    FXRequirement(
                        statement.metadata.currency,
                        target_currency,
                        statement.period.start,
                    )
                )
            if statement.metadata.closing_balance is not None:
                requirements.add(
                    FXRequirement(
                        statement.metadata.currency,
                        target_currency,
                        statement.period.end,
                    )
                )
        requirements.update(
            FXRequirement(currency, target_currency, datetime.now(UTC).date())
            for currency in self.account_currencies.values()
            if currency != target_currency
        )
        for row in self.transactions.values():
            foreign = row.enrichment.get("foreign_spend")
            if not isinstance(foreign, dict):
                continue
            currency = foreign.get("currency")
            amount = foreign.get("amount")
            if (
                isinstance(currency, str)
                and len(currency) == 3
                and currency.isalpha()
                and currency != row.currency_native
                and isinstance(amount, str)
            ):
                requirements.add(
                    FXRequirement(currency.upper(), row.currency_native, row.booked_date)
                )
        return tuple(sorted(requirements, key=lambda item: (item.base, item.quote, item.as_of)))

    def rebuild_base_currency(self, *, target_currency: str, max_staleness_days: int) -> int:
        del max_staleness_days
        self.base_currency = _currency_code(target_currency)
        return len(self.transactions)

    def expire_lease_for_test(self, job_id: str) -> None:
        job, _claimed_at = self._inflight[job_id]
        self._inflight[job_id] = (job, datetime.now(UTC) - timedelta(days=1))

    def _assert_lease(self, job: Job) -> None:
        active = self._inflight.get(job.id)
        if active is None or job.claim_token is None or active[0].claim_token != job.claim_token:
            raise LeaseLostError(f"lease for job {job.id} is no longer owned")

    def persist_statement(
        self,
        *,
        account_id: str,
        source_file_key: str,
        metadata: StatementMetadata,
        rows: tuple[CanonicalTransaction, ...],
        reconciliation: ReconciliationResult,
    ) -> PersistResult:
        if metadata.period_start is None or metadata.period_end is None:
            raise ValueError("statement period is required for persistence")
        # Validate every authoritative OFX identity before mutating this
        # in-memory test double, mirroring the transactionality of PostgreSQL.
        for row in rows:
            self._existing_memory_ofx_transaction(account_id=account_id, row=row)
        self.account_refs[account_id] = _resolve_account_reference(
            self.account_refs.get(account_id), metadata.account_ref_masked
        )
        statement_id = f"statement:{account_id}:{source_file_key}"
        existing_statement = self.statements.get(statement_id)
        merged_metadata = metadata
        effective_reconciliation = reconciliation
        effective_status = reconciliation.status
        if existing_statement is not None and (
            metadata.opening_balance is None or metadata.closing_balance is None
        ):
            merged_metadata = metadata.model_copy(
                update={
                    "opening_balance": existing_statement.metadata.opening_balance,
                    "closing_balance": existing_statement.metadata.closing_balance,
                }
            )
            effective_reconciliation = existing_statement.reconciliation
            effective_status = existing_statement.status
        self.statements[statement_id] = MemoryStatement(
            account_id=account_id,
            metadata=merged_metadata,
            period=StatementPeriod(metadata.period_start, metadata.period_end),
            reconciliation=effective_reconciliation,
            status=effective_status,
        )
        added = 0
        for row in rows:
            if self._existing_memory_ofx_transaction(account_id=account_id, row=row):
                continue
            persisted_row = self._apply_memory_merchant_mapping(row)
            existing = self.transactions.get(persisted_row.dedup_hash)
            if existing is None:
                self.transactions[persisted_row.dedup_hash] = persisted_row
                self.transaction_accounts[persisted_row.dedup_hash] = account_id
                added += 1
            elif persisted_row.posted_date is not None:
                if (
                    existing.posted_date is not None
                    and existing.posted_date != persisted_row.posted_date
                ):
                    raise ValueError(
                        "statement processed date conflicts with an existing transaction"
                    )
                if existing.posted_date is None:
                    self.transactions[persisted_row.dedup_hash] = existing.model_copy(
                        update={"posted_date": persisted_row.posted_date}
                    )
        records = [
            (
                existing_id,
                existing.period,
                existing.status,
            )
            for existing_id, existing in self.statements.items()
            if existing.account_id == account_id
        ]
        statuses, gaps = _account_coverage_statuses(records)
        for existing_id, status in statuses.items():
            self.statements[existing_id].status = status
        return PersistResult(
            statement_id,
            added,
            len(rows) - added,
            statuses[statement_id],
            gaps,
        )

    def _apply_memory_merchant_mapping(self, row: CanonicalTransaction) -> CanonicalTransaction:
        flow = _canonical_flow_type(row)
        learned = self.merchant_category_mappings.get((row.merchant_key, flow))
        if learned is None:
            return row
        category, source, confidence = learned
        if category.kind != _category_kind_for_flow(flow):
            return row
        if source is CategorySource.AI and row.category_source is not CategorySource.FALLBACK:
            return row
        return row.model_copy(
            update={
                "category_name": category.name,
                "category_kind": category.kind,
                "category_source": source,
                "category_confidence": confidence,
            }
        )

    def _existing_memory_ofx_transaction(
        self, *, account_id: str, row: CanonicalTransaction
    ) -> bool:
        if row.external_ref is None or "ofx_transaction_type" not in row.enrichment:
            return False
        existing = next(
            (
                candidate
                for dedup_hash, candidate in self.transactions.items()
                if self.transaction_accounts.get(dedup_hash) == account_id
                and candidate.external_ref == row.external_ref
                and "ofx_transaction_type" in candidate.enrichment
            ),
            None,
        )
        if existing is None:
            return False
        if (
            existing.booked_date != row.booked_date
            or existing.amount_native != row.amount_native
            or existing.currency_native != row.currency_native
        ):
            raise ValueError("OFX FITID conflicts with an existing transaction")
        return True


def _resolve_account_reference(current: str | None, discovered: str | None) -> str | None:
    if discovered is None:
        return current
    if current is None or _is_placeholder_account_reference(current):
        return discovered
    current_suffix = _account_reference_suffix(current)
    discovered_suffix = _account_reference_suffix(discovered)
    if current.strip().casefold() == discovered.strip().casefold():
        return current
    if current_suffix is not None and discovered_suffix is not None:
        if current_suffix == discovered_suffix:
            return current
        if (len(current_suffix) == 4 or len(discovered_suffix) == 4) and current_suffix[
            -4:
        ] == discovered_suffix[-4:]:
            return discovered if len(discovered_suffix) > len(current_suffix) else current
    raise ValueError("statement account reference does not match selected account")


def _is_placeholder_account_reference(value: str) -> bool:
    suffix = _account_reference_suffix(value)
    return suffix is not None and set(suffix) == {"0"}


def _account_reference_suffix(value: str) -> str | None:
    match = re.search(r"(\d{4,6})\s*$", value.strip())
    return match.group(1) if match is not None else None


def _account_coverage_statuses(
    records: list[tuple[str, StatementPeriod, str]],
) -> tuple[dict[str, str], tuple[StatementPeriod, ...]]:
    """Return per-statement status and global missing periods for one account."""

    ordered = sorted(records, key=lambda item: (item[1].start, item[1].end, item[0]))
    if not ordered:
        return {}, ()
    gap_followers: set[str] = set()
    gaps: list[StatementPeriod] = []
    covered_until = ordered[0][1].end
    for statement_id, period, _status in ordered[1:]:
        expected = covered_until + timedelta(days=1)
        if period.start > expected:
            gaps.append(StatementPeriod(expected, period.start - timedelta(days=1)))
            gap_followers.add(statement_id)
        covered_until = max(covered_until, period.end)

    statuses: dict[str, str] = {}
    for statement_id, _period, previous_status in ordered:
        # A prior gap is a coverage overlay on an arithmetically valid statement.
        arithmetic_status = "ok" if previous_status == "gap" else previous_status
        if arithmetic_status in {"mismatch", "pending"}:
            statuses[statement_id] = arithmetic_status
        elif statement_id in gap_followers:
            statuses[statement_id] = "gap"
        else:
            statuses[statement_id] = "ok"
    return statuses, tuple(gaps)


def _claim_token(job: Job) -> UUID:
    if job.claim_token is None:
        raise LeaseLostError(f"job {job.id} has no claim token")
    try:
        return UUID(job.claim_token)
    except ValueError as exc:
        raise LeaseLostError(f"job {job.id} has an invalid claim token") from exc


def _currency_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a three-letter ISO-style code")
    return code


def _category_kind_for_flow(flow_type: FlowType) -> CategoryKind:
    expected: dict[FlowType, CategoryKind] = {
        FlowType.SPEND: "spend",
        FlowType.INCOME: "income",
        FlowType.TRANSFER: "transfer",
        FlowType.REFUND: "transfer",
        FlowType.FEE: "fee",
    }
    return expected[flow_type]


def _canonical_flow_type(row: CanonicalTransaction) -> FlowType:
    categorization = row.enrichment.get("categorization")
    if isinstance(categorization, dict):
        raw_flow = categorization.get("flow_type")
        if isinstance(raw_flow, str):
            return FlowType(raw_flow)
    if row.direction.value in {"fee", "interest"}:
        return FlowType.FEE
    if row.direction.value == "refund":
        return FlowType.REFUND
    if row.direction.value == "payment":
        return FlowType.TRANSFER
    return FlowType.SPEND
