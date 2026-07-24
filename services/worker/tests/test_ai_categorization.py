from __future__ import annotations

import json
from typing import Any

import pytest

from worker.ai_categorization import (
    AICategorizationService,
    CategoryOption,
    UnresolvedMerchantFlow,
)
from worker.models import FlowType
from worker.repository import InMemoryRepository


class _Provider:
    provider_name = "test-provider"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def model_name(self, model_tier: str) -> str:
        return f"test-{model_tier}"

    def complete(self, **request: Any) -> dict[str, object]:
        self.calls.append(request)
        return self.responses.pop(0)


def _repository() -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.categories = [
        CategoryOption(id="00000000-0000-4000-8000-00000000c001", name="Other", kind="spend"),
        CategoryOption(
            id="00000000-0000-4000-8000-00000000c00e",
            name="Refunds",
            kind="transfer",
        ),
    ]
    repository.unresolved_merchant_flows = [
        UnresolvedMerchantFlow(
            merchant_id="00000000-0000-4000-8000-000000000201",
            merchant_key="novel coffee shop",
            flow_type=FlowType.SPEND,
        ),
        UnresolvedMerchantFlow(
            merchant_id="00000000-0000-4000-8000-000000000202",
            merchant_key="novel return",
            flow_type=FlowType.REFUND,
        ),
    ]
    return repository


def test_ai_categorization_minimizes_prompt_and_applies_threshold() -> None:
    repository = _repository()
    first, second = repository.unresolved_merchant_flows
    provider = _Provider(
        [
            {
                "assignments": [
                    {
                        "key": str(first.opaque_key),
                        "category_id": repository.categories[0].id,
                        "confidence": 0.95,
                        "new_category_proposal": None,
                    },
                    {
                        "key": str(second.opaque_key),
                        "category_id": repository.categories[1].id,
                        "confidence": 0.5,
                        "new_category_proposal": None,
                    },
                ]
            }
        ]
    )

    result = AICategorizationService(
        provider=provider,  # type: ignore[arg-type]
        repository=repository,
        auto_apply_threshold=0.85,
    ).run({})

    assert result == {
        "scanned": 2,
        "auto_applied": 1,
        "proposals_created": 1,
        "unchanged": 0,
    }
    assert repository.ai_mappings[(first.merchant_id, FlowType.SPEND)] == (
        repository.categories[0].id,
        0.95,
    )
    assert second.opaque_key in repository.categorization_proposals
    prompt = provider.calls[0]["messages"][0]["content"]
    parsed_prompt = json.loads(prompt)
    assert parsed_prompt["merchants"] == [
        {
            "key": str(first.opaque_key),
            "merchant": "novel coffee shop",
            "flow_type": "spend",
        },
        {
            "key": str(second.opaque_key),
            "merchant": "novel return",
            "flow_type": "refund",
        },
    ]
    for forbidden in ("amount", "balance", "account_id", "transaction_id", "booked_date"):
        assert forbidden not in prompt
    assert first.merchant_id not in prompt
    assert provider.calls[0]["model_tier"] == "cheap"

    # Learned mappings and pending proposals make a repeated backfill a no-op.
    assert AICategorizationService(
        provider=provider,  # type: ignore[arg-type]
        repository=repository,
        auto_apply_threshold=0.85,
    ).run({}) == {
        "scanned": 0,
        "auto_applied": 0,
        "proposals_created": 0,
        "unchanged": 0,
    }
    assert len(provider.calls) == 1


def test_new_category_is_always_a_review_proposal() -> None:
    repository = _repository()
    repository.unresolved_merchant_flows = repository.unresolved_merchant_flows[:1]
    item = repository.unresolved_merchant_flows[0]
    provider = _Provider(
        [
            {
                "assignments": [
                    {
                        "key": str(item.opaque_key),
                        "category_id": None,
                        "confidence": 0.99,
                        "new_category_proposal": {"name": "Specialty Shops", "kind": "spend"},
                    }
                ]
            }
        ]
    )

    result = AICategorizationService(
        provider=provider,  # type: ignore[arg-type]
        repository=repository,
    ).run()

    assert result["auto_applied"] == 0
    proposal = repository.categorization_proposals[item.opaque_key]
    assert proposal["proposed_category_id"] is None
    assert proposal["proposed_category_name"] == "Specialty Shops"


def test_invalid_category_id_fails_without_persistence() -> None:
    repository = _repository()
    repository.unresolved_merchant_flows = repository.unresolved_merchant_flows[:1]
    item = repository.unresolved_merchant_flows[0]
    provider = _Provider(
        [
            {
                "assignments": [
                    {
                        "key": str(item.opaque_key),
                        "category_id": "00000000-0000-4000-8000-00000000ffff",
                        "confidence": 0.99,
                        "new_category_proposal": None,
                    }
                ]
            }
        ]
    )

    with pytest.raises(ValueError, match="unknown category"):
        AICategorizationService(
            provider=provider,  # type: ignore[arg-type]
            repository=repository,
        ).run()

    assert repository.ai_mappings == {}
    assert repository.categorization_proposals == {}


def test_late_invalid_assignment_cannot_leave_earlier_partial_write() -> None:
    repository = _repository()
    first, second = repository.unresolved_merchant_flows
    provider = _Provider(
        [
            {
                "assignments": [
                    {
                        "key": str(first.opaque_key),
                        "category_id": repository.categories[0].id,
                        "confidence": 0.99,
                        "new_category_proposal": None,
                    },
                    {
                        "key": str(second.opaque_key),
                        "category_id": "00000000-0000-4000-8000-00000000ffff",
                        "confidence": 0.99,
                        "new_category_proposal": None,
                    },
                ]
            }
        ]
    )

    with pytest.raises(ValueError, match="unknown category"):
        AICategorizationService(
            provider=provider,  # type: ignore[arg-type]
            repository=repository,
        ).run()

    assert repository.ai_mappings == {}
    assert repository.categorization_proposals == {}


class _EchoBatchProvider:
    provider_name = "batch-provider"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def model_name(self, model_tier: str) -> str:
        return f"batch-{model_tier}"

    def complete(self, **request: Any) -> dict[str, object]:
        self.calls.append(request)
        payload = json.loads(request["messages"][0]["content"])
        category_id = payload["categories"][0]["id"]
        return {
            "assignments": [
                {
                    "key": merchant["key"],
                    "category_id": category_id,
                    "confidence": 0.99,
                    "new_category_proposal": None,
                }
                for merchant in payload["merchants"]
            ]
        }


def test_categorization_drains_more_than_one_batch() -> None:
    repository = InMemoryRepository()
    repository.categories = [
        CategoryOption(id="00000000-0000-4000-8000-00000000c001", name="Other", kind="spend")
    ]
    repository.unresolved_merchant_flows = [
        UnresolvedMerchantFlow(
            merchant_id=f"00000000-0000-4000-8000-{index:012d}",
            merchant_key=f"merchant {index}",
            flow_type=FlowType.SPEND,
        )
        for index in range(5)
    ]
    provider = _EchoBatchProvider()

    result = AICategorizationService(
        provider=provider,  # type: ignore[arg-type]
        repository=repository,
        batch_size=2,
    ).run()

    assert result == {
        "scanned": 5,
        "auto_applied": 5,
        "proposals_created": 0,
        "unchanged": 0,
    }
    batch_sizes = [
        len(json.loads(call["messages"][0]["content"])["merchants"]) for call in provider.calls
    ]
    assert batch_sizes == [2, 2, 1]
