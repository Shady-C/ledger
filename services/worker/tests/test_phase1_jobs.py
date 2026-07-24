from __future__ import annotations

from typing import Any

import pytest

from worker.fx import MissingFXRateError
from worker.models import FileIngestResult
from worker.pipeline import JobRunner
from worker.repository import InMemoryRepository, Job, LeaseLostError


class _Pipeline:
    def process_file(self, *, account_id: str, file_key: str) -> FileIngestResult:
        del account_id, file_key
        return FileIngestResult(file_key="unused", adapter="unused", status="done")


class _Task:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {}
        self.payloads: list[dict[str, object]] = []

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        self.payloads.append(payload)
        return self.result


@pytest.mark.parametrize(
    ("kind", "payload", "handler_name", "result"),
    [
        (
            "categorize",
            {"mode": "incremental"},
            "categorization",
            {"scanned": 1, "auto_applied": 1, "proposals_created": 0, "unchanged": 0},
        ),
        (
            "fx_refresh",
            {"target_base_currency": "CAD"},
            "fx_refresh",
            {"base_currency": "CAD", "quote_currencies": ["USD"], "rates_stored": 1},
        ),
        (
            "base_currency_rebuild",
            {"target_base_currency": "CAD"},
            "base_currency_rebuild",
            {
                "previous_base_currency": "CAD",
                "target_base_currency": "CAD",
                "transactions_updated": 2,
                "settings_updated": True,
            },
        ),
        (
            "analytics_refresh",
            {"mode": "incremental"},
            "analytics_refresh",
            {
                "generation": 1,
                "mode": "incremental",
                "source_watermark": None,
                "aggregate_count": 0,
                "recurring_series_count": 0,
                "finding_count": 0,
                "duration_ms": 1,
            },
        ),
    ],
)
def test_runner_dispatches_every_service_job_kind(
    kind: str,
    payload: dict[str, object],
    handler_name: str,
    result: dict[str, object],
) -> None:
    repository = InMemoryRepository([Job(id=f"{kind}-job", kind=kind, payload=payload)])
    task = _Task(result)
    handlers: dict[str, Any] = {
        "categorization": None,
        "fx_refresh": None,
        "base_currency_rebuild": None,
        "analytics_refresh": None,
    }
    handlers[handler_name] = task
    runner = JobRunner(
        jobs=repository,
        pipeline=_Pipeline(),  # type: ignore[arg-type]
        **handlers,
    )

    assert runner.run_once() is True

    assert repository.completed[f"{kind}-job"] == {**result, "status": "done"}
    assert task.payloads == [payload]


class _FailingTask:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        del payload
        self.calls += 1
        raise RuntimeError("temporary provider outage")


def test_service_job_gets_three_retries_then_fails() -> None:
    repository = InMemoryRepository([Job(id="retry", kind="categorize", payload={})])
    task = _FailingTask()
    runner = JobRunner(
        jobs=repository,
        pipeline=_Pipeline(),  # type: ignore[arg-type]
        categorization=task,
    )

    assert [runner.run_once() for _ in range(4)] == [True, True, True, True]

    assert task.calls == 4
    assert repository.retry_events == ["retry", "retry", "retry", "retry"]
    assert repository.failed["retry"] == "categorize processing failed"
    assert repository.jobs == []


def test_invalid_base_rebuild_payload_fails_without_retry() -> None:
    repository = InMemoryRepository([Job(id="invalid", kind="base_currency_rebuild", payload={})])
    runner = JobRunner(
        jobs=repository,
        pipeline=_Pipeline(),  # type: ignore[arg-type]
        base_currency_rebuild=_Task(),
    )

    runner.run_once()

    assert repository.failed["invalid"] == "invalid base_currency_rebuild job payload"
    assert repository.retry_events == []


class _MissingRatePipeline:
    def process_file(self, *, account_id: str, file_key: str) -> FileIngestResult:
        del account_id, file_key
        raise MissingFXRateError("temporary")


def test_ingest_missing_rate_requeues_without_partial_rollback() -> None:
    repository = InMemoryRepository(
        [Job(id="fx-ingest", kind="ingest", payload={"account_id": "a", "file_keys": ["x"]})]
    )
    runner = JobRunner(
        jobs=repository,
        pipeline=_MissingRatePipeline(),  # type: ignore[arg-type]
    )

    runner.run_once()

    assert repository.retry_events == ["fx-ingest"]
    assert repository.failed == {}
    assert repository.jobs[0].retry_count == 1


@pytest.mark.parametrize("kind", ["categorize", "fx_refresh", "analytics_refresh"])
def test_followup_enqueue_during_claim_forces_exactly_one_rerun(kind: str) -> None:
    payload = (
        {"target_base_currency": "CAD"}
        if kind == "fx_refresh"
        else {"mode": "incremental", "analytics_run_id": "run-one"}
        if kind == "analytics_refresh"
        else {}
    )
    repository = InMemoryRepository([Job(id="coalesced", kind=kind, payload=payload)])

    first = repository.claim_next_job(timeout_seconds=60)
    assert first is not None
    if kind == "categorize":
        repository.enqueue_categorization_job()
    elif kind == "fx_refresh":
        repository.enqueue_fx_refresh_job(target_base_currency="CAD")
    else:
        repository.enqueue_analytics_refresh_job(mode="incremental")
    # A heartbeat after the racing enqueue must not erase the rerun marker.
    repository.heartbeat_job(first)
    repository.complete_job(first, {"first": True}, needs_ai=False)

    assert repository.completed == {}
    assert len(repository.jobs) == 1
    second = repository.claim_next_job(timeout_seconds=60)
    assert second is not None
    assert "rerun_requested" not in second.payload
    if kind == "analytics_refresh":
        assert "analytics_run_id" not in second.payload
    repository.complete_job(second, {"second": True}, needs_ai=False)

    assert repository.jobs == []
    assert repository.completed["coalesced"] == {"second": True, "status": "done"}


def test_queued_followup_coalesces_without_an_unnecessary_second_run() -> None:
    repository = InMemoryRepository([Job(id="queued", kind="categorize", payload={})])

    repository.enqueue_categorization_job()
    claimed = repository.claim_next_job(timeout_seconds=60)
    assert claimed is not None
    assert "rerun_requested" not in claimed.payload
    repository.complete_job(claimed, {}, needs_ai=False)

    assert repository.jobs == []
    assert repository.completed["queued"]["status"] == "done"


def test_full_analytics_request_upgrades_a_queued_incremental_refresh() -> None:
    repository = InMemoryRepository(
        [Job(id="analytics", kind="analytics_refresh", payload={"mode": "incremental"})]
    )

    repository.enqueue_analytics_refresh_job(mode="full")
    claimed = repository.claim_next_job(timeout_seconds=60)

    assert claimed is not None
    assert claimed.payload == {"mode": "full"}
    repository.complete_job(claimed, {}, needs_ai=False)
    assert repository.jobs == []


def test_full_analytics_request_during_claim_forces_a_full_rerun() -> None:
    repository = InMemoryRepository(
        [
            Job(
                id="analytics",
                kind="analytics_refresh",
                payload={"mode": "incremental", "analytics_run_id": "first-run"},
            )
        ]
    )
    claimed = repository.claim_next_job(timeout_seconds=60)
    assert claimed is not None

    repository.enqueue_analytics_refresh_job(mode="full")
    repository.complete_job(claimed, {}, needs_ai=False)
    rerun = repository.claim_next_job(timeout_seconds=60)

    assert rerun is not None
    assert rerun.payload == {"mode": "full"}


def test_incremental_analytics_request_does_not_downgrade_a_queued_full_refresh() -> None:
    repository = InMemoryRepository(
        [Job(id="analytics", kind="analytics_refresh", payload={"mode": "full"})]
    )

    repository.enqueue_analytics_refresh_job(mode="incremental")
    claimed = repository.claim_next_job(timeout_seconds=60)

    assert claimed is not None
    assert claimed.payload == {"mode": "full"}


def test_repeated_stale_claims_consume_the_bounded_retry_budget() -> None:
    repository = InMemoryRepository([Job(id="stale", kind="categorize", payload={})])
    previous = repository.claim_next_job(timeout_seconds=60)
    assert previous is not None

    for expected_retry in (1, 2, 3):
        repository.expire_lease_for_test("stale")
        reclaimed = repository.claim_next_job(timeout_seconds=60)
        assert reclaimed is not None
        assert reclaimed.retry_count == expected_retry
        with pytest.raises(LeaseLostError):
            repository.complete_job(previous, {}, needs_ai=False)
        previous = reclaimed

    repository.expire_lease_for_test("stale")
    assert repository.claim_next_job(timeout_seconds=60) is None
    assert repository.failed["stale"] == ("job lease expired after retry budget was exhausted")
