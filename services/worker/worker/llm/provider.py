"""Provider boundary reserved for Phase 1 ambiguity handling."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


ModelTier = Literal["cheap", "capable"]


class LLMProvider(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, object] | None = None,
        model_tier: ModelTier,
    ) -> dict[str, object]: ...


class LLMDisabledError(RuntimeError):
    pass


class DisabledLLMProvider:
    """Default Phase 0 implementation: makes accidental model calls fail closed."""

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, object] | None = None,
        model_tier: ModelTier,
    ) -> dict[str, object]:
        del system, messages, schema, model_tier
        raise LLMDisabledError("LLM calls are disabled in Phase 0")
