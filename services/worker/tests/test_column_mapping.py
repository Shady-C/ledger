from __future__ import annotations

import json
from typing import Any

from worker.column_mapping import AIColumnMappingService
from worker.llm.provider import DisabledLLMProvider
from worker.models import AccountKind, ParsedFile, ParseStatus
from worker.pipeline import IngestionPipeline
from worker.repository import InMemoryRepository
from worker.storage import MemoryObjectStore


class _MappingProvider:
    provider_name = "mapping-test"

    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def model_name(self, model_tier: str) -> str:
        return f"mapping-{model_tier}"

    def complete(self, **request: Any) -> dict[str, object]:
        self.calls.append(request)
        return self.response


def _mapping(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "booked_date": "When",
        "posted_date": None,
        "description": "Who",
        "amount": "Value",
        "debit": None,
        "credit": None,
        "currency": "Coin",
        "reference": "Ref",
        "date_order": "ymd",
        "decimal_separator": "dot",
        "amount_semantics": "credit_card_positive_charges",
        "default_currency": "CAD",
    }
    value.update(overrides)
    return value


def test_unknown_csv_mapping_redacts_samples_and_reuses_cached_adapter() -> None:
    content = b"""When,Who,Value,Coin,Ref
2026-01-13,Private Novel Merchant,12.34,CAD,R-1
2026-01-14,Second Private Merchant,20.00,CAD,R-2
2026-01-15,Third Private Merchant,30.00,CAD,R-3
2026-01-16,Fourth Private Merchant,40.00,CAD,R-4
2026-01-17,Fifth Private Merchant,50.00,CAD,R-5
2026-01-18,Sixth Private Merchant,60.00,CAD,R-6
"""
    repository = InMemoryRepository()
    provider = _MappingProvider(_mapping())
    mapper = AIColumnMappingService(provider=provider, store=repository)  # type: ignore[arg-type]
    file = ParsedFile(name="novel.csv", content=content)

    first = mapper.parse(
        file,
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )
    second = mapper.parse(
        file,
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    assert first.status is ParseStatus.READY
    assert len(first.rows) == 6
    assert second.rows == first.rows
    assert len(provider.calls) == 1
    assert len(repository.adapter_mappings) == 1
    prompt = json.loads(provider.calls[0]["messages"][0]["content"])
    assert prompt["headers"] == ["When", "Who", "Value", "Coin", "Ref"]
    assert len(prompt["sample_rows"]) == 5
    serialized = json.dumps(prompt)
    assert "Private Novel Merchant" not in serialized
    assert "12.34" not in serialized
    assert "R-1" not in serialized
    assert provider.calls[0]["model_tier"] == "capable"


def test_invalid_ai_mapping_remains_needs_ai_and_persists_nothing() -> None:
    content = b"When,Who,Value,Coin\n2026-01-13,Private Merchant,12.34,CAD\n"
    repository = InMemoryRepository()
    provider = _MappingProvider(_mapping(debit="Value"))
    mapper = AIColumnMappingService(provider=provider, store=repository)  # type: ignore[arg-type]
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({"novel.csv": content}),
        repository=repository,
        column_mapper=mapper,
    )

    result = pipeline.process_file(account_id="card", file_key="novel.csv")

    assert result.status == "needs_ai"
    assert result.added == 0
    assert repository.transactions == {}
    assert repository.statements == {}
    assert repository.adapter_mappings == {}


def test_ai_mapping_rejects_currency_but_derives_sign_semantics_from_account() -> None:
    file = ParsedFile(
        name="novel.csv",
        content=(b"When,Who,Value,Coin,Ref\n2026-01-13,Private Merchant,12.34,TZS,R-1\n"),
    )
    repository = InMemoryRepository()
    currency_provider = _MappingProvider(_mapping(default_currency="TZS"))
    currency_result = AIColumnMappingService(
        provider=currency_provider,  # type: ignore[arg-type]
        store=repository,
    ).parse(
        file,
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    asset_provider = _MappingProvider(_mapping())
    asset_result = AIColumnMappingService(
        provider=asset_provider,  # type: ignore[arg-type]
        store=repository,
    ).parse(
        file.model_copy(update={"content": file.content.replace(b"TZS", b"CAD")}),
        account_id="asset",
        account_kind=AccountKind.CHEQUING,
        native_currency="CAD",
    )

    assert currency_result.status is ParseStatus.NEEDS_AI
    assert asset_result.status is ParseStatus.READY
    assert str(asset_result.rows[0].amount_native) == "12.34"
    assert asset_result.rows[0].direction.value == "credit"


def test_unknown_tabular_format_without_api_key_is_stable_needs_ai() -> None:
    content = b"When,Who,Value\n2026-01-13,Private Merchant,12.34\n"
    repository = InMemoryRepository()
    mapper = AIColumnMappingService(provider=DisabledLLMProvider(), store=repository)
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({"novel.csv": content}),
        repository=repository,
        column_mapper=mapper,
    )

    result = pipeline.process_file(account_id="card", file_key="novel.csv")

    assert result.status == "needs_ai"
    assert result.reason == "AI column mapping could not be validated"
    assert repository.transactions == {}


def test_adapter_fingerprint_varies_by_account_kind_and_native_currency() -> None:
    repository = InMemoryRepository()
    provider = _MappingProvider(_mapping())
    mapper = AIColumnMappingService(provider=provider, store=repository)  # type: ignore[arg-type]
    cad = ParsedFile(
        name="novel.csv",
        content=b"When,Who,Value,Coin,Ref\n2026-01-13,Vendor,12.34,CAD,R-1\n",
    )

    assert (
        mapper.parse(
            cad,
            account_id="same-institution",
            account_kind=AccountKind.CREDIT_CARD,
            native_currency="CAD",
        ).status
        is ParseStatus.READY
    )
    provider.response = _mapping(default_currency="TZS")
    assert (
        mapper.parse(
            cad.model_copy(update={"content": cad.content.replace(b"CAD", b"TZS")}),
            account_id="same-institution",
            account_kind=AccountKind.CREDIT_CARD,
            native_currency="TZS",
        ).status
        is ParseStatus.READY
    )
    provider.response = _mapping(default_currency="CAD", amount_semantics="asset_positive_inflows")
    asset = mapper.parse(
        cad,
        account_id="same-institution",
        account_kind=AccountKind.CHEQUING,
        native_currency="CAD",
    )

    assert asset.status is ParseStatus.READY
    assert asset.rows[0].direction.value == "credit"
    assert len(provider.calls) == 3
    assert len(repository.adapter_mappings) == 3


def test_decimal_convention_is_inferred_locally_even_when_ai_guesses_dot() -> None:
    content = b"When;Who;Value;Coin;Ref\n2026-01-13;Private Merchant;1234,56;CAD;R-1\n"
    repository = InMemoryRepository()
    provider = _MappingProvider(_mapping(decimal_separator="dot"))
    result = AIColumnMappingService(
        provider=provider,  # type: ignore[arg-type]
        store=repository,
    ).parse(
        ParsedFile(name="comma.csv", content=content),
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    assert result.status is ParseStatus.READY
    assert str(result.rows[0].amount_native) == "1234.56"
    saved = next(iter(repository.adapter_mappings.values()))
    assert saved["decimal_separator"] == "comma"


def test_conflicting_numeric_conventions_are_not_cached() -> None:
    content = (
        b"When;Who;Value;Coin;Ref\n"
        b"2026-01-13;First Merchant;12.34;CAD;R-1\n"
        b"2026-01-14;Second Merchant;12,34;CAD;R-2\n"
    )
    repository = InMemoryRepository()
    result = AIColumnMappingService(
        provider=_MappingProvider(_mapping()),  # type: ignore[arg-type]
        store=repository,
    ).parse(
        ParsedFile(name="mixed.csv", content=content),
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    assert result.status is ParseStatus.NEEDS_AI
    assert repository.adapter_mappings == {}


def test_ambiguous_slash_dates_are_rejected_instead_of_trusting_ai() -> None:
    repository = InMemoryRepository()
    ambiguous = ParsedFile(
        name="ambiguous.csv",
        content=(
            b"When,Who,Value,Coin,Ref\n"
            b"01/02/2026,Private Merchant,12.34,CAD,R-1\n"
            b"03/04/2026,Second Merchant,20.00,CAD,R-2\n"
        ),
    )
    result = AIColumnMappingService(
        provider=_MappingProvider(_mapping(date_order="mdy")),  # type: ignore[arg-type]
        store=repository,
    ).parse(
        ambiguous,
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    assert result.status is ParseStatus.NEEDS_AI
    assert repository.adapter_mappings == {}


def test_unambiguous_slash_date_evidence_overrides_ai_order() -> None:
    repository = InMemoryRepository()
    result = AIColumnMappingService(
        provider=_MappingProvider(_mapping(date_order="mdy")),  # type: ignore[arg-type]
        store=repository,
    ).parse(
        ParsedFile(
            name="dmy.csv",
            content=(b"When,Who,Value,Coin,Ref\n13/02/2026,Private Merchant,12.34,CAD,R-1\n"),
        ),
        account_id="card",
        account_kind=AccountKind.CREDIT_CARD,
        native_currency="CAD",
    )

    assert result.status is ParseStatus.READY
    assert result.rows[0].booked_date.isoformat() == "2026-02-13"
    saved = next(iter(repository.adapter_mappings.values()))
    assert saved["date_order"] == "dmy"
