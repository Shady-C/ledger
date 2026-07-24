"""PostgreSQL job queue and canonical-ledger persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from worker.models import AccountKind, CanonicalTransaction, StatementMetadata
from worker.reconcile import ReconciliationResult, StatementPeriod


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    payload: dict[str, Any]
    claim_token: str | None = None


class LeaseLostError(RuntimeError):
    """Raised when a superseded worker tries to mutate a reclaimed job."""


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
    def get_account_kind(self, account_id: str) -> AccountKind: ...

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


class PostgresRepository(LedgerRepository, JobRepository):
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be blank")
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def claim_next_job(self, *, timeout_seconds: float) -> Job | None:
        claim_token = uuid4()
        query = """
            WITH next_job AS (
                SELECT id
                FROM job
                WHERE status = 'queued'
                   OR (
                       status = 'claimed'
                       AND claimed_at < now() - make_interval(secs => %s)
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
                finished_at = NULL, result = NULL, error = NULL, updated_at = now()
            FROM next_job
            WHERE target.id = next_job.id
            RETURNING target.id::text AS id, target.kind, target.payload,
                      target.claim_token::text AS claim_token
        """
        with self._connect() as connection, connection.cursor() as cursor:
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
                SET status = %s, result = %s, error = NULL,
                    finished_at = now(), claim_token = NULL, updated_at = now()
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

    def get_account_kind(self, account_id: str) -> AccountKind:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT kind FROM account WHERE id = %s", (account_id,))
            row = cursor.fetchone()
        if row is None:
            raise ValueError("account does not exist")
        return AccountKind(str(row["kind"]))

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
            statement_id = self._get_or_create_statement(
                cursor,
                account_id=account_id,
                source_file_key=source_file_key,
                metadata=metadata,
                reconcile_status=reconciliation.status,
            )
            added = 0
            for row in rows:
                category_id = self._category_id(cursor, row.category_name, row.category_kind)
                merchant_id = self._merchant_id(cursor, row.merchant_name, row.merchant_key)
                cursor.execute(
                    """
                    INSERT INTO txn (
                        account_id, statement_id, booked_date, posted_date,
                        description_raw, merchant_id, category_id,
                        amount_native, currency_native, amount_base, currency_base,
                        fx_rate, fx_rate_date, external_ref, dedup_hash, direction,
                        enrichment
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
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
                    ),
                )
                added += int(cursor.fetchone() is not None)
            reconcile_status, gaps = self._refresh_coverage(
                cursor,
                account_id=account_id,
                current_statement_id=statement_id,
                current_arithmetic_status=reconciliation.status,
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
    ) -> str:
        cursor.execute(
            """
            INSERT INTO statement (
                account_id, period_start, period_end, opening_balance,
                closing_balance, currency, source_file_key, reconcile_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, source_file_key) DO UPDATE
            SET updated_at = statement.updated_at
            RETURNING id::text AS id
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
        return str(created["id"])

    @staticmethod
    def _category_id(cursor: psycopg.Cursor[Any], name: str, kind: str) -> str:
        cursor.execute(
            "SELECT id::text AS id FROM category "
            "WHERE parent_id IS NULL AND lower(name) = lower(%s)",
            (name,),
        )
        if row := cursor.fetchone():
            return str(row["id"])
        cursor.execute(
            "INSERT INTO category (name, kind) VALUES (%s, %s) RETURNING id::text AS id",
            (name, kind),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("category insert did not return an id")
        return str(row["id"])

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
        default_account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> None:
        self.jobs = list(jobs or [])
        self.claimed: list[str] = []
        self.completed: dict[str, dict[str, Any]] = {}
        self.failed: dict[str, str] = {}
        self.transactions: dict[str, CanonicalTransaction] = {}
        self.statements: dict[str, MemoryStatement] = {}
        self.account_kinds = dict(account_kinds or {})
        self.default_account_kind = default_account_kind
        self.heartbeat_count = 0
        self._inflight: dict[str, tuple[Job, datetime]] = {}

    def claim_next_job(self, *, timeout_seconds: float) -> Job | None:
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
        job = replace(candidate, claim_token=str(uuid4()))
        self._inflight[job.id] = (job, now)
        self.claimed.append(job.id)
        return job

    def heartbeat_job(self, job: Job) -> None:
        self._assert_lease(job)
        self._inflight[job.id] = (job, datetime.now(UTC))
        self.heartbeat_count += 1

    def complete_job(self, job: Job, result: dict[str, Any], *, needs_ai: bool) -> None:
        self._assert_lease(job)
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

    def get_account_kind(self, account_id: str) -> AccountKind:
        return self.account_kinds.get(account_id, self.default_account_kind)

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
        statement_id = f"statement:{account_id}:{source_file_key}"
        self.statements[statement_id] = MemoryStatement(
            account_id=account_id,
            metadata=metadata,
            period=StatementPeriod(metadata.period_start, metadata.period_end),
            reconciliation=reconciliation,
            status=reconciliation.status,
        )
        added = 0
        for row in rows:
            if row.dedup_hash not in self.transactions:
                self.transactions[row.dedup_hash] = row
                added += 1
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
