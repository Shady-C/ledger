"""Privacy-minimized AI tail for unresolved merchant/flow pairs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from worker.llm.provider import LLMProvider
from worker.models import FlowType

CategoryKind = Literal["spend", "income", "transfer", "fee"]
_OPAQUE_NAMESPACE = UUID("664c8a3a-955c-5b6e-8e3c-7bfbad21ba71")


@dataclass(frozen=True, slots=True)
class CategoryOption:
    id: str
    name: str
    kind: CategoryKind


@dataclass(frozen=True, slots=True)
class UnresolvedMerchantFlow:
    merchant_id: str
    merchant_key: str
    flow_type: FlowType

    @property
    def opaque_key(self) -> UUID:
        return uuid5(_OPAQUE_NAMESPACE, f"{self.merchant_id}:{self.flow_type.value}")


class NewCategoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: CategoryKind


class CategoryAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: UUID
    category_id: str | None
    confidence: float = Field(ge=0, le=1)
    new_category_proposal: NewCategoryProposal | None

    @model_validator(mode="after")
    def exactly_one_target(self) -> CategoryAssignment:
        if (self.category_id is None) == (self.new_category_proposal is None):
            raise ValueError("assignment requires exactly one existing or proposed category")
        return self


class CategoryAssignments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignments: tuple[CategoryAssignment, ...]


class CategorizationRepository(Protocol):
    def list_active_categories(self) -> tuple[CategoryOption, ...]: ...

    def list_unresolved_merchant_flows(
        self, *, limit: int
    ) -> tuple[UnresolvedMerchantFlow, ...]: ...

    def apply_ai_category(
        self,
        *,
        merchant_id: str,
        flow_type: FlowType,
        category_id: str,
        confidence: float,
    ) -> int: ...

    def record_categorization_proposal(
        self,
        *,
        opaque_key: UUID,
        merchant_id: str,
        flow_type: FlowType,
        proposed_category_id: str | None,
        proposed_category_name: str | None,
        proposed_category_kind: CategoryKind | None,
        confidence: float,
        provider: str,
        model: str,
        raw_assignment: dict[str, object],
    ) -> bool: ...


_ASSIGNMENTS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "format": "uuid"},
                    "category_id": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "new_category_proposal": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "kind": {
                                        "type": "string",
                                        "enum": ["spend", "income", "transfer", "fee"],
                                    },
                                },
                                "required": ["name", "kind"],
                                "additionalProperties": False,
                            },
                            {"type": "null"},
                        ]
                    },
                },
                "required": [
                    "key",
                    "category_id",
                    "confidence",
                    "new_category_proposal",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}


class AICategorizationService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        repository: CategorizationRepository,
        auto_apply_threshold: float | None = None,
        batch_size: int = 200,
    ) -> None:
        threshold = (
            auto_apply_threshold
            if auto_apply_threshold is not None
            else float(os.getenv("AI_CATEGORY_AUTO_APPLY_THRESHOLD", "0.85"))
        )
        if not 0 <= threshold <= 1:
            raise ValueError("AI_CATEGORY_AUTO_APPLY_THRESHOLD must be between 0 and 1")
        if batch_size <= 0:
            raise ValueError("categorization batch size must be positive")
        self.provider = provider
        self.repository = repository
        self.auto_apply_threshold = threshold
        self.batch_size = batch_size

    def run(self, payload: dict[str, object] | None = None) -> dict[str, object]:
        del payload
        categories = self.repository.list_active_categories()
        totals: dict[str, object] = {
            "scanned": 0,
            "auto_applied": 0,
            "proposals_created": 0,
            "unchanged": 0,
        }
        seen: set[UUID] = set()
        while True:
            candidates = self.repository.list_unresolved_merchant_flows(limit=self.batch_size)
            unresolved = tuple(item for item in candidates if item.opaque_key not in seen)
            if not unresolved:
                return totals
            if not categories:
                raise ValueError("categorization requires at least one active category")
            seen.update(item.opaque_key for item in unresolved)
            result = self._run_batch(categories=categories, unresolved=unresolved)
            for key in totals:
                totals[key] = cast(int, totals[key]) + result[key]

    def _run_batch(
        self,
        *,
        categories: tuple[CategoryOption, ...],
        unresolved: tuple[UnresolvedMerchantFlow, ...],
    ) -> dict[str, int]:

        response = self.provider.complete(
            system=(
                "Categorize each normalized merchant/flow pair. Select an allowed category ID "
                "or propose one category. Do not infer or return financial values."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "merchants": [
                                {
                                    "key": str(item.opaque_key),
                                    "merchant": item.merchant_key,
                                    "flow_type": item.flow_type.value,
                                }
                                for item in unresolved
                            ],
                            "categories": [
                                {"id": item.id, "name": item.name, "kind": item.kind}
                                for item in categories
                            ],
                        },
                        separators=(",", ":"),
                    ),
                }
            ],
            schema=_ASSIGNMENTS_SCHEMA,
            model_tier="cheap",
        )
        assignments = CategoryAssignments.model_validate(response).assignments
        by_key = {item.opaque_key: item for item in unresolved}
        if len(assignments) != len(by_key) or {item.key for item in assignments} != set(by_key):
            raise ValueError("categorization response must assign every requested opaque key once")
        if len({item.key for item in assignments}) != len(assignments):
            raise ValueError("categorization response contains duplicate opaque keys")

        allowed = {item.id: item for item in categories}
        actions: list[
            tuple[
                CategoryAssignment,
                UnresolvedMerchantFlow,
                CategoryOption | None,
                NewCategoryProposal | None,
            ]
        ] = []
        for assignment in assignments:
            merchant = by_key[assignment.key]
            category = allowed.get(assignment.category_id or "")
            proposal = assignment.new_category_proposal
            if category is not None:
                _validate_category_kind(category.kind, merchant.flow_type)
            elif assignment.category_id is not None:
                raise ValueError("categorization response references an unknown category ID")
            if proposal is not None:
                _validate_category_kind(proposal.kind, merchant.flow_type)
            actions.append((assignment, merchant, category, proposal))

        # Validate the entire structured response before allowing the first DB
        # mutation, so one bad tail assignment cannot leave partial AI writes.
        applied = 0
        proposed = 0
        unchanged = 0
        for assignment, merchant, category, proposal in actions:
            if category is not None and assignment.confidence >= self.auto_apply_threshold:
                updated = self.repository.apply_ai_category(
                    merchant_id=merchant.merchant_id,
                    flow_type=merchant.flow_type,
                    category_id=category.id,
                    confidence=assignment.confidence,
                )
                applied += int(updated > 0)
                unchanged += int(updated == 0)
                continue
            created = self.repository.record_categorization_proposal(
                opaque_key=assignment.key,
                merchant_id=merchant.merchant_id,
                flow_type=merchant.flow_type,
                proposed_category_id=category.id if category is not None else None,
                proposed_category_name=proposal.name if proposal is not None else None,
                proposed_category_kind=proposal.kind if proposal is not None else None,
                confidence=assignment.confidence,
                provider=self.provider.provider_name,
                model=self.provider.model_name("cheap"),
                raw_assignment=assignment.model_dump(mode="json"),
            )
            proposed += int(created)
            unchanged += int(not created)
        return {
            "scanned": len(assignments),
            "auto_applied": applied,
            "proposals_created": proposed,
            "unchanged": unchanged,
        }


def _validate_category_kind(kind: CategoryKind, flow: FlowType) -> None:
    expected: dict[FlowType, CategoryKind] = {
        FlowType.SPEND: "spend",
        FlowType.INCOME: "income",
        FlowType.TRANSFER: "transfer",
        FlowType.REFUND: "transfer",
        FlowType.FEE: "fee",
    }
    if kind != expected[flow]:
        raise ValueError(f"category kind {kind!r} is incompatible with {flow.value!r}")
