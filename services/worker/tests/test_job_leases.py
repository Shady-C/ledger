from __future__ import annotations

import time

import pytest

from worker.models import FileIngestResult
from worker.pipeline import JobRunner
from worker.repository import InMemoryRepository, Job, LeaseLostError


def test_stale_claim_is_recovered_with_new_token_and_old_owner_is_fenced() -> None:
    repository = InMemoryRepository(
        [Job(id="lease-job", kind="ingest", payload={"account_id": "a", "file_keys": ["x"]})]
    )
    first = repository.claim_next_job(timeout_seconds=60)
    assert first is not None
    repository.expire_lease_for_test(first.id)

    second = repository.claim_next_job(timeout_seconds=60)

    assert second is not None
    assert second.id == first.id
    assert second.claim_token != first.claim_token
    with pytest.raises(LeaseLostError, match="no longer owned"):
        repository.complete_job(first, {"added": 0, "skipped": 0, "files": []}, needs_ai=False)
    with pytest.raises(LeaseLostError, match="no longer owned"):
        repository.fail_job(first, "old worker")

    repository.complete_job(second, {"added": 0, "skipped": 0, "files": []}, needs_ai=False)
    assert repository.completed[second.id]["status"] == "done"


def test_heartbeat_renews_active_lease() -> None:
    repository = InMemoryRepository([Job(id="heartbeat-job", kind="ingest", payload={})])
    claimed = repository.claim_next_job(timeout_seconds=60)
    assert claimed is not None

    repository.heartbeat_job(claimed)

    assert repository.claim_next_job(timeout_seconds=60) is None
    assert repository.heartbeat_count == 1


class _SlowPipeline:
    def process_file(self, *, account_id: str, file_key: str) -> FileIngestResult:
        del account_id
        time.sleep(0.25)
        return FileIngestResult(
            file_key=file_key,
            adapter="slow_test",
            status="done",
        )


def test_runner_heartbeats_while_a_file_is_processing() -> None:
    repository = InMemoryRepository(
        [
            Job(
                id="slow-job",
                kind="ingest",
                payload={"account_id": "account", "file_keys": ["slow.csv"]},
            )
        ]
    )

    JobRunner(
        jobs=repository,
        pipeline=_SlowPipeline(),  # type: ignore[arg-type]
        timeout_seconds=0.3,
    ).run_once()

    assert repository.completed["slow-job"]["status"] == "done"
    assert repository.heartbeat_count >= 2
