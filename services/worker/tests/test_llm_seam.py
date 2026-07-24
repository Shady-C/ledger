from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from worker.llm.anthropic import AnthropicProvider
from worker.llm.provider import DisabledLLMProvider, LLMDisabledError, LLMResponseError
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


class _Messages:
    def __init__(self, *, stop_reason: str = "end_turn", text: str = '{"ok":true}') -> None:
        self.stop_reason = stop_reason
        self.text = text
        self.request: dict[str, Any] | None = None

    def create(self, **request: Any) -> object:
        self.request = request
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def test_anthropic_uses_native_structured_outputs_and_pinned_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = _Messages()
    client = SimpleNamespace(messages=messages)
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **_kw: client))
    monkeypatch.delenv("ANTHROPIC_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_CAPABLE", raising=False)
    provider = AnthropicProvider(api_key="test")

    result = provider.complete(
        system="structured",
        messages=[{"role": "user", "content": "safe"}],
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        model_tier="cheap",
    )

    assert result == {"ok": True}
    assert provider.model_name("cheap") == "claude-haiku-4-5-20251001"
    assert provider.model_name("capable") == "claude-sonnet-5"
    assert messages.request is not None
    assert messages.request["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        }
    }
    assert "Return only JSON" not in messages.request["system"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_rejects_refusal_or_truncated_structured_output(
    monkeypatch: pytest.MonkeyPatch, stop_reason: str
) -> None:
    messages = _Messages(stop_reason=stop_reason, text="not schema JSON")
    client = SimpleNamespace(messages=messages)
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **_kw: client))
    provider = AnthropicProvider(api_key="test")

    with pytest.raises(LLMResponseError):
        provider.complete(
            system="structured",
            messages=[{"role": "user", "content": "safe"}],
            schema={"type": "object"},
            model_tier="cheap",
        )
