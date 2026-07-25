from __future__ import annotations

import pytest

from worker.models import FlowType
from worker.repository import PostgresRepository


class _Cursor:
    def __init__(self, responses: list[dict[str, object] | None]) -> None:
        self.responses = responses
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> None:
        self.executed.append((query, parameters))

    def fetchone(self) -> dict[str, object] | None:
        return self.responses.pop(0)

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor

    def __enter__(self) -> _Connection:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


def test_deterministic_category_resolution_uses_active_kind_and_protected_fallback() -> None:
    cursor = _Cursor([None, {"id": "other-id"}])

    category_id, matched = PostgresRepository._category_id(  # type: ignore[arg-type]
        cursor, "Groceries", "spend"
    )

    assert (category_id, matched) == ("other-id", False)
    expected_query, expected_parameters = cursor.executed[0]
    fallback_query, _fallback_parameters = cursor.executed[1]
    assert "archived_at IS NULL" in expected_query
    assert "kind = %s" in expected_query
    assert expected_parameters == ("Groceries", "spend")
    assert "is_protected" in fallback_query
    assert "INSERT" not in " ".join(query for query, _parameters in cursor.executed)


def test_learned_category_resolution_requires_active_flow_compatible_kind() -> None:
    cursor = _Cursor([None])

    resolved = PostgresRepository._learned_category(  # type: ignore[arg-type]
        cursor,
        merchant_id="merchant-id",
        flow_type=FlowType.REFUND,
        deterministic_source="fallback",
    )

    assert resolved is None
    query, parameters = cursor.executed[0]
    assert "category.archived_at IS NULL" in query
    assert "category.kind = %s" in query
    assert parameters == ("merchant-id", "refund", "transfer", "fallback")


def test_followup_enqueue_retries_when_conflicting_job_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First UPDATE sees no active job; first INSERT conflicts with a concurrent
    # winner. That winner then finishes before the second UPDATE, so the second
    # INSERT must be attempted and accepted.
    cursor = _Cursor([None, None, None, {"id": "replacement"}])
    repository = PostgresRepository("postgresql://acceptance.invalid/ledger")
    monkeypatch.setattr(repository, "_connect", lambda: _Connection(cursor))

    repository.enqueue_analytics_refresh_job(mode="full")

    statements = [query for query, _parameters in cursor.executed]
    assert len(statements) == 4
    assert ["UPDATE job" in query for query in statements] == [True, False, True, False]
    assert ["INSERT INTO job" in query for query in statements] == [
        False,
        True,
        False,
        True,
    ]


def test_followup_enqueue_turnover_retry_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _Cursor([None] * 10)
    repository = PostgresRepository("postgresql://acceptance.invalid/ledger")
    monkeypatch.setattr(repository, "_connect", lambda: _Connection(cursor))

    with pytest.raises(RuntimeError, match="could not enqueue or coalesce"):
        repository.enqueue_categorization_job()

    assert len(cursor.executed) == 10
