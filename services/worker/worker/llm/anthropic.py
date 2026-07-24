"""Config-driven Anthropic structured-output implementation."""

from __future__ import annotations

import json
import os
from typing import Any

from worker.llm.provider import LLMResponseError, Message, ModelTier


class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cheap_model: str | None = None,
        capable_model: str | None = None,
    ) -> None:
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is required")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("install ledger-worker[llm] to use Anthropic") from exc
        self._client: Any = anthropic.Anthropic(api_key=key)
        self._models: dict[ModelTier, str] = {
            "cheap": cheap_model
            or os.getenv("ANTHROPIC_MODEL_CHEAP")
            or "claude-haiku-4-5-20251001",
            "capable": capable_model or os.getenv("ANTHROPIC_MODEL_CAPABLE") or "claude-sonnet-5",
        }

    def model_name(self, model_tier: ModelTier) -> str:
        return self._models[model_tier]

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, object] | None = None,
        model_tier: ModelTier,
    ) -> dict[str, object]:
        request: dict[str, Any] = {
            "model": self._models[model_tier],
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
        }
        if schema is not None:
            request["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        response = self._client.messages.create(
            **request,
        )
        stop_reason = str(response.stop_reason or "")
        if stop_reason == "refusal":
            raise LLMResponseError("Anthropic refused the structured-output request")
        if stop_reason in {"max_tokens", "model_context_window_exceeded"}:
            raise LLMResponseError("Anthropic structured output was truncated")
        if stop_reason not in {"end_turn", "stop_sequence"}:
            raise LLMResponseError(f"Anthropic returned unexpected stop reason: {stop_reason}")
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("Anthropic returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise LLMResponseError("provider response must be a JSON object")
        return value
