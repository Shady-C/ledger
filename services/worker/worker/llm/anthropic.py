"""Config-driven Anthropic implementation, not instantiated by Phase 0."""

from __future__ import annotations

import json
import os
from typing import Any

from worker.llm.provider import Message, ModelTier


class AnthropicProvider:
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
        self._models = {
            "cheap": cheap_model or os.getenv("ANTHROPIC_MODEL_CHEAP", "claude-3-5-haiku-latest"),
            "capable": capable_model or os.getenv("ANTHROPIC_MODEL_CAPABLE", "claude-sonnet-4-0"),
        }

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, object] | None = None,
        model_tier: ModelTier,
    ) -> dict[str, object]:
        system_prompt = system
        if schema is not None:
            system_prompt += "\nReturn only JSON matching this schema:\n" + json.dumps(schema)
        response = self._client.messages.create(
            model=self._models[model_tier],
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("provider response must be a JSON object")
        return value
