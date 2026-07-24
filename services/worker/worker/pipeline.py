"""Parse → normalize → FX → categorize → dedup → reconcile → persist."""

from __future__ import annotations

import logging
import mimetypes
import threading
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from worker.adapters import (
    AmexXlsxAdapter,
    GenericCsvAdapter,
    GenericXlsxAdapter,
    OfxAdapter,
    PdfTableAdapter,
)
from worker.adapters.base import Adapter, AdapterError
from worker.categorize import categorize
from worker.column_mapping import AIColumnMappingService
from worker.dedup import transaction_dedup_hash
from worker.fx import FXRateProvider, MissingFXRateError, pending_fx_stamp, stamp_fx
from worker.models import CanonicalTransaction, FileIngestResult, ParsedFile, ParseStatus
from worker.reconcile import reconcile_statement
from worker.repository import (
    BaseCurrencyChangedError,
    Job,
    JobRepository,
    LeaseLostError,
    LedgerRepository,
)
from worker.storage import ObjectStore, StatementEnvelopeError

LOGGER = logging.getLogger(__name__)


class UnsupportedStatementError(AdapterError):
    pass


class JobTask(Protocol):
    def run(self, payload: dict[str, object]) -> dict[str, object]: ...


class AdapterRegistry:
    def __init__(
        self, adapters: Iterable[Adapter] | None = None, *, threshold: float = 0.4
    ) -> None:
        self.adapters = tuple(
            adapters
            or (
                OfxAdapter(),
                AmexXlsxAdapter(),
                GenericCsvAdapter(),
                GenericXlsxAdapter(),
                PdfTableAdapter(),
            )
        )
        self.threshold = threshold

    def select(self, file: ParsedFile) -> Adapter:
        scored = sorted(
            ((adapter.detect(file), adapter) for adapter in self.adapters),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored or scored[0][0] < self.threshold:
            raise UnsupportedStatementError(f"no deterministic adapter recognized {file.name!r}")
        top_score, top_adapter = scored[0]
        LOGGER.info(
            "selected adapter",
            extra={"adapter": top_adapter.name, "confidence": top_score, "file": file.name},
        )
        return top_adapter


class IngestionPipeline:
    def __init__(
        self,
        *,
        store: ObjectStore,
        repository: LedgerRepository,
        base_currency: str | None = None,
        fx_provider: FXRateProvider | None = None,
        registry: AdapterRegistry | None = None,
        column_mapper: AIColumnMappingService | None = None,
        auto_enqueue_categorization: bool = False,
        auto_enqueue_fx_refresh: bool = True,
        auto_enqueue_analytics: bool = True,
    ) -> None:
        self.store = store
        self.repository = repository
        self.base_currency = base_currency.upper() if base_currency is not None else None
        if self.base_currency is not None and self.base_currency != "CAD":
            raise ValueError("Phase 2 reporting currency is fixed to CAD")
        self.fx_provider = fx_provider
        self.registry = registry or AdapterRegistry()
        self.column_mapper = column_mapper
        self.auto_enqueue_categorization = auto_enqueue_categorization
        self.auto_enqueue_fx_refresh = auto_enqueue_fx_refresh
        self.auto_enqueue_analytics = auto_enqueue_analytics

    def process_file(self, *, account_id: str, file_key: str) -> FileIngestResult:
        account = self.repository.get_account_profile(account_id)
        account_kind = account.kind
        base_currency = self.base_currency or self.repository.get_base_currency()
        if base_currency != "CAD":
            raise ValueError("Phase 2 reporting currency is fixed to CAD")
        content = self.store.read(file_key)
        file = ParsedFile(
            name=PurePosixPath(file_key).name,
            content=content,
            content_type=mimetypes.guess_type(file_key)[0],
        )
        try:
            adapter = self.registry.select(file)
            parsed = adapter.parse(file, account_kind=account_kind)
            adapter_name = adapter.name
        except UnsupportedStatementError:
            if self.column_mapper is None or file.extension not in {".csv", ".xlsx"}:
                raise
            parsed = self.column_mapper.parse(
                file,
                account_id=account_id,
                account_kind=account_kind,
                native_currency=account.native_currency,
            )
            adapter_name = parsed.adapter
        if parsed.status is ParseStatus.NEEDS_AI:
            return FileIngestResult(
                file_key=file_key,
                adapter=adapter_name,
                status="needs_ai",
                reason=parsed.reason,
            )

        currencies = {row.currency_native for row in parsed.rows}
        if (
            currencies != {account.native_currency}
            or parsed.statement.currency != account.native_currency
        ):
            raise AdapterError("statement currency does not match the selected account")

        reconciliation = reconcile_statement(parsed.statement, parsed.rows)
        canonical: list[CanonicalTransaction] = []
        for row in parsed.rows:
            try:
                fx = stamp_fx(row, base_currency=base_currency, provider=self.fx_provider)
            except MissingFXRateError:
                # Native statement truth is independently useful and reconciles
                # without a reporting-currency quote. A refresh job can fill the
                # nullable CAD layer later.
                fx = pending_fx_stamp(base_currency=base_currency)
            category = categorize(row, account_kind=account_kind)
            enrichment = {
                **row.enrichment,
                "categorization": {
                    "confidence": category.confidence,
                    "matched_rule": category.matched_rule,
                    "needs_review": category.matched_rule is None,
                    "flow_type": category.flow_type.value,
                },
                "fx_source": fx.source,
            }
            canonical.append(
                CanonicalTransaction(
                    **row.model_dump(exclude={"enrichment"}),
                    enrichment=enrichment,
                    amount_base=fx.amount_base,
                    currency_base=fx.currency_base,
                    fx_rate=fx.rate,
                    fx_rate_date=fx.rate_date,
                    merchant_name=category.merchant_name,
                    merchant_key=category.merchant_key,
                    category_name=category.category_name,
                    category_kind=category.category_kind,
                    category_source=category.source,
                    category_confidence=category.confidence,
                    dedup_hash=transaction_dedup_hash(
                        account_id=account_id,
                        booked_date=row.booked_date,
                        amount_native=row.amount_native,
                        currency_native=row.currency_native,
                        description_raw=row.description_raw,
                        external_ref=row.external_ref,
                    ),
                )
            )

        persisted = self.repository.persist_statement(
            account_id=account_id,
            source_file_key=file_key,
            metadata=parsed.statement,
            rows=tuple(canonical),
            reconciliation=reconciliation,
        )
        source_changed = persisted.added > 0 or persisted.updated > 0
        if self.auto_enqueue_categorization and persisted.added:
            try:
                self.repository.enqueue_categorization_job()
            except Exception:
                # Categorization is explicitly outside the financial transaction;
                # a provider/queue outage cannot undo a reconciled statement.
                LOGGER.exception(
                    "could not enqueue post-ingest categorization",
                    extra={"file": file_key},
                )
        needs_fx_refresh = account.native_currency != base_currency or any(
            row.original_currency is not None and row.original_currency != row.currency_native
            for row in parsed.rows
        )
        if self.auto_enqueue_fx_refresh and source_changed and needs_fx_refresh:
            try:
                self.repository.enqueue_fx_refresh_job(target_base_currency=base_currency)
            except Exception:
                LOGGER.exception(
                    "could not enqueue post-ingest FX refresh",
                    extra={"file": file_key},
                )
        if self.auto_enqueue_analytics and source_changed:
            try:
                self.repository.enqueue_analytics_refresh_job(mode="incremental")
            except Exception:
                LOGGER.exception(
                    "could not enqueue post-ingest analytics refresh",
                    extra={"file": file_key},
                )
        reconcile_payload: dict[str, object] = dict(reconciliation.as_dict())
        reconcile_payload["status"] = persisted.reconcile_status
        reconcile_payload["coverage_gaps"] = [
            {"start": gap.start.isoformat(), "end": gap.end.isoformat()}
            for gap in persisted.coverage_gaps
        ]
        return FileIngestResult(
            file_key=file_key,
            adapter=adapter_name,
            status="done",
            added=persisted.added,
            skipped=persisted.skipped,
            statement_id=persisted.statement_id,
            reconcile=reconcile_payload,
        )


class JobRunner:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        pipeline: IngestionPipeline,
        timeout_seconds: float = 900,
        categorization: JobTask | None = None,
        fx_refresh: JobTask | None = None,
        base_currency_rebuild: JobTask | None = None,
        analytics_refresh: JobTask | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("job timeout must be positive")
        self.jobs = jobs
        self.pipeline = pipeline
        self.timeout_seconds = timeout_seconds
        self.handlers = {
            "categorize": categorization,
            "fx_refresh": fx_refresh,
            "base_currency_rebuild": base_currency_rebuild,
            "analytics_refresh": analytics_refresh,
        }

    def run_once(self) -> bool:
        """Claim and process at most one job; return whether work was claimed."""

        job = self.jobs.claim_next_job(timeout_seconds=self.timeout_seconds)
        if job is None:
            return False
        if job.kind != "ingest":
            return self._run_service_job(job)
        try:
            account_id, file_keys = _ingest_payload(job.payload)
        except Exception:
            LOGGER.exception("invalid job", extra={"job_id": job.id})
            self._fail_if_owned(job, "invalid ingest job payload")
            return True

        heartbeat = _LeaseHeartbeat(
            jobs=self.jobs,
            job=job,
            interval_seconds=max(0.1, min(self.timeout_seconds / 3, 30)),
        )
        try:
            heartbeat.start()
            files: list[FileIngestResult] = []
            retryable_error: Exception | None = None
            for file_key in file_keys:
                heartbeat.checkpoint()
                try:
                    outcome = self.pipeline.process_file(
                        account_id=account_id,
                        file_key=file_key,
                    )
                except Exception as exc:
                    if isinstance(exc, MissingFXRateError | BaseCurrencyChangedError):
                        retryable_error = exc
                    LOGGER.warning(
                        "file ingestion failed",
                        extra={"job_id": job.id, "file": file_key},
                        exc_info=True,
                    )
                    outcome = FileIngestResult(
                        file_key=file_key,
                        adapter="unavailable",
                        status="failed",
                        reason=_safe_failure_reason(exc),
                    )
                files.append(outcome)
                heartbeat.checkpoint()
            heartbeat.stop()
            heartbeat.checkpoint()
            needs_ai = any(result.status == "needs_ai" for result in files)
            failed = any(result.status == "failed" for result in files)
            result = {
                "added": sum(file.added for file in files),
                "skipped": sum(file.skipped for file in files),
                "files": [file.model_dump(mode="json") for file in files],
            }
            if failed and retryable_error is not None:
                self._retry_if_owned(job, "required FX rate is temporarily unavailable")
            elif failed:
                self.jobs.fail_job(
                    job,
                    "one or more statement files failed",
                    result=result,
                )
            else:
                self.jobs.complete_job(job, result, needs_ai=needs_ai)
            LOGGER.info(
                "job completed",
                extra={"job_id": job.id, "added": result["added"], "skipped": result["skipped"]},
            )
        except LeaseLostError:
            LOGGER.warning(
                "job lease lost; leaving terminal update to the new owner", extra={"job_id": job.id}
            )
        except Exception:
            LOGGER.exception("job failed", extra={"job_id": job.id})
            self._fail_if_owned(job, "internal job processing error")
        finally:
            heartbeat.stop()
        return True

    def _run_service_job(self, job: Job) -> bool:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self._fail_if_owned(job, f"unsupported or unconfigured job kind: {job.kind}")
            return True
        try:
            _validate_service_payload(job.kind, job.payload)
        except ValueError:
            LOGGER.exception("invalid job", extra={"job_id": job.id})
            self._fail_if_owned(job, f"invalid {job.kind} job payload")
            return True

        heartbeat = _LeaseHeartbeat(
            jobs=self.jobs,
            job=job,
            interval_seconds=max(0.1, min(self.timeout_seconds / 3, 30)),
        )
        try:
            heartbeat.start()
            result = handler.run(job.payload)
            heartbeat.stop()
            heartbeat.checkpoint()
            self.jobs.complete_job(job, result, needs_ai=False)
        except LeaseLostError:
            LOGGER.warning(
                "job lease lost; leaving terminal update to the new owner",
                extra={"job_id": job.id},
            )
        except Exception:
            LOGGER.exception("retryable service job failure", extra={"job_id": job.id})
            heartbeat.stop()
            self._retry_if_owned(job, f"{job.kind} processing failed")
        finally:
            heartbeat.stop()
        return True

    def _fail_if_owned(self, job: Job, reason: str) -> None:
        try:
            self.jobs.fail_job(job, reason)
        except LeaseLostError:
            LOGGER.warning("job failure was fenced by a newer lease", extra={"job_id": job.id})

    def _retry_if_owned(self, job: Job, reason: str) -> None:
        try:
            queued = self.jobs.retry_job(job, reason)
            LOGGER.warning(
                "job requeued" if queued else "job retry budget exhausted",
                extra={"job_id": job.id},
            )
        except LeaseLostError:
            LOGGER.warning("job retry was fenced by a newer lease", extra={"job_id": job.id})


def _ingest_payload(payload: dict[str, object]) -> tuple[str, tuple[str, ...]]:
    account_id = payload.get("account_id")
    raw_keys = payload.get("file_keys")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("ingest payload requires account_id")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("ingest payload requires a non-empty file_keys array")
    if not all(isinstance(key, str) and key.strip() for key in raw_keys):
        raise ValueError("every file key must be a non-empty string")
    return account_id, tuple(raw_keys)


def _validate_service_payload(kind: str, payload: dict[str, object]) -> None:
    if kind == "categorize":
        return
    if kind == "analytics_refresh":
        mode = payload.get("mode", "incremental")
        if mode not in {"full", "incremental"}:
            raise ValueError("analytics_refresh mode must be full or incremental")
        run_id = payload.get("analytics_run_id")
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise ValueError("analytics_refresh analytics_run_id must be a non-empty string")
        if isinstance(run_id, str):
            try:
                UUID(run_id)
            except ValueError as error:
                raise ValueError("analytics_refresh analytics_run_id must be a UUID") from error
        return
    base_currency = payload.get("target_base_currency", payload.get("base_currency"))
    if kind == "base_currency_rebuild" and not isinstance(base_currency, str):
        raise ValueError("base_currency_rebuild requires base_currency")
    if base_currency is not None and (
        not isinstance(base_currency, str)
        or len(base_currency.strip()) != 3
        or not base_currency.strip().isalpha()
    ):
        raise ValueError(f"{kind} base_currency must be a three-letter code")


class _LeaseHeartbeat:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        job: Job,
        interval_seconds: float,
    ) -> None:
        self.jobs = jobs
        self.job = job
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.jobs.heartbeat_job(self.job)
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-heartbeat-{self.job.id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))

    def checkpoint(self) -> None:
        if self._error is not None:
            raise self._error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.jobs.heartbeat_job(self.job)
            except Exception as exc:
                self._error = exc
                self._stop.set()


def _safe_failure_reason(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "source object is unavailable"
    if isinstance(error, StatementEnvelopeError):
        return "source object encryption could not be verified"
    if isinstance(error, MissingFXRateError):
        return "required FX rate is unavailable"
    if isinstance(error, BaseCurrencyChangedError):
        return "base currency changed during ingestion"
    if isinstance(error, (AdapterError, ValidationError, ValueError)):
        return "statement format or monetary values are invalid"
    return "internal file processing error"
