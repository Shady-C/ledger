"""Provider boundary reserved for Phase 1 ambiguity handling."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


ModelTier = Literal["cheap", "capable"]


class LLMProvider(Protocol):
    provider_name: str

    def model_name(self, model_tier: ModelTier) -> str: ...

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


class LLMResponseError(RuntimeError):
    """The provider completed a call without a usable structured response."""


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

    provider_name = "disabled"

    def model_name(self, model_tier: ModelTier) -> str:
        return f"disabled-{model_tier}"
