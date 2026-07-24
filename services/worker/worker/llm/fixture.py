"""Deterministic provider used only by explicit smoke/CI configuration."""

from __future__ import annotations

import json

from worker.llm.provider import LLMResponseError, Message, ModelTier


class FixtureLLMProvider:
    provider_name = "fixture"

    def model_name(self, model_tier: ModelTier) -> str:
        return f"fixture-{model_tier}"

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: dict[str, object] | None = None,
        model_tier: ModelTier,
    ) -> dict[str, object]:
        del system, schema, model_tier
        if len(messages) != 1:
            raise LLMResponseError("fixture provider expects one user message")
        payload = json.loads(messages[0]["content"])
        if not isinstance(payload, dict) or "merchants" not in payload:
            raise LLMResponseError("fixture provider only supports categorization")
        merchants = payload.get("merchants")
        categories = payload.get("categories")
        if not isinstance(merchants, list) or not isinstance(categories, list):
            raise LLMResponseError("fixture categorization payload is invalid")
        by_kind: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for raw in categories:
            if not isinstance(raw, dict):
                continue
            category_id = str(raw.get("id", ""))
            kind = str(raw.get("kind", ""))
            name = str(raw.get("name", "")).casefold()
            by_kind.setdefault(kind, category_id)
            by_name[name] = category_id
        expected_kind = {
            "spend": "spend",
            "income": "income",
            "transfer": "transfer",
            "refund": "transfer",
            "fee": "fee",
        }
        assignments: list[dict[str, object]] = []
        for raw in merchants:
            if not isinstance(raw, dict):
                raise LLMResponseError("fixture merchant is invalid")
            flow = str(raw.get("flow_type", ""))
            merchant = str(raw.get("merchant", "")).casefold()
            preferred = _preferred_category(merchant)
            selected = by_name.get(preferred) if preferred is not None else None
            if selected is None:
                selected = by_kind.get(expected_kind.get(flow, ""))
            if not selected:
                raise LLMResponseError("fixture taxonomy lacks a compatible category")
            assignments.append(
                {
                    "key": str(raw.get("key", "")),
                    "category_id": selected,
                    "confidence": 0.99,
                    "new_category_proposal": None,
                }
            )
        return {"assignments": assignments}


def _preferred_category(merchant: str) -> str | None:
    matches = (
        (("grocery", "market", "supermarket"), "groceries"),
        (("coffee", "cafe", "restaurant"), "dining"),
        (("hotel", "airline", "flight"), "travel"),
        (("uber", "taxi", "transit"), "transport"),
    )
    for tokens, category in matches:
        if any(token in merchant for token in tokens):
            return category
    return None
