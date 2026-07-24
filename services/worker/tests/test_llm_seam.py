from __future__ import annotations

import pytest

from worker.llm.provider import DisabledLLMProvider, LLMDisabledError
from worker.models import ParseResult, ParseStatus, StatementMetadata
from worker.pipeline import AdapterRegistry, IngestionPipeline, JobRunner
from worker.repository import InMemoryRepository, Job
from worker.storage import MemoryObjectStore


def test_phase_zero_provider_fails_closed() -> None:
    with pytest.raises(LLMDisabledError, match="disabled"):
        DisabledLLMProvider().complete(
            system="do not run",
            messages=[{"role": "user", "content": "unused"}],
            model_tier="cheap",
        )


class NeedsAiAdapter:
    format = "pdf"
    name = "needs_ai_test"

    def detect(self, _file) -> float:
        return 1.0

    def parse(self, _file, *, account_kind) -> ParseResult:
        del account_kind
        return ParseResult(
            adapter=self.name,
            status=ParseStatus.NEEDS_AI,
            statement=StatementMetadata(),
            reason="synthetic irregular layout",
        )


def test_needs_ai_is_a_stable_job_result_and_does_not_invoke_llm() -> None:
    repository = InMemoryRepository(
        [
            Job(
                id="needs-ai-job",
                kind="ingest",
                payload={"account_id": "account", "file_keys": ["irregular.pdf"]},
            )
        ]
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({"irregular.pdf": b"%PDF synthetic"}),
        repository=repository,
        registry=AdapterRegistry((NeedsAiAdapter(),)),
    )

    JobRunner(jobs=repository, pipeline=pipeline).run_once()

    result = repository.completed["needs-ai-job"]
    assert result["status"] == "needs_ai"
    assert result["added"] == 0
    assert result["skipped"] == 0
    assert result["files"] == [
        {
            "file_key": "irregular.pdf",
            "adapter": "needs_ai_test",
            "status": "needs_ai",
            "added": 0,
            "skipped": 0,
            "statement_id": None,
            "reconcile": None,
            "reason": "synthetic irregular layout",
        }
    ]
