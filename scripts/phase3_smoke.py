"""Exercise the Phase 3 Grounded Ask flow with deterministic local providers.

The stack must be running with ``ASK_ENABLED=true``, ``ASK_PROVIDER_MODE=stub``,
and ``WORKER_PROVIDER_MODE=stub``. This script retains the complete Phase 2
smoke first, adds synthetic recurring evidence, then verifies canonical and
adversarial Ask outcomes without printing questions, answers, or evidence.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import phase0_smoke
import phase1_smoke
import phase2_smoke

ALL_FIXTURE_FIRST_DATE = date(2026, 1, 3)
TZ_FIXTURE_FIRST_DATE = date(2026, 5, 3)
ALL_COVERAGE = {
    "status": "complete",
    "valuedTransactionCount": 16,
    "pendingFxCount": 0,
    "pendingByCurrency": [],
}
TZ_COVERAGE = {
    "status": "complete",
    "valuedTransactionCount": 7,
    "pendingFxCount": 0,
    "pendingByCurrency": [],
}
FX_COVERAGE = {
    "status": "complete",
    "valuedTransactionCount": 4,
    "pendingFxCount": 0,
    "pendingByCurrency": [],
}


def ask_api_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Call an Ask endpoint while keeping response bodies out of failures."""

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"accept": "application/json"}
    if body is not None:
        headers["content-type"] = "application/json"
    if method != "GET":
        headers["origin"] = phase0_smoke.BASE_URL
    request = Request(
        f"{phase0_smoke.BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=phase0_smoke.HTTP_TIMEOUT_SECONDS) as response:
            parsed = json.loads(response.read())
    except HTTPError as error:
        error.read()
        raise AssertionError(f"Ask endpoint returned HTTP {error.code}") from error
    if not isinstance(parsed, dict):
        raise TypeError("Ask endpoint returned a non-object response")
    return cast(dict[str, Any], parsed)


def ask(
    question: str,
    *,
    market: str = "ALL",
    history: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    return ask_api_json(
        "/api/ask",
        method="POST",
        payload={
            "question": question,
            "market": market,
            "timeZone": "UTC",
            "history": history or [],
        },
    )


def execute_plan(response: dict[str, Any]) -> dict[str, Any]:
    plan = response.get("plan")
    if not isinstance(plan, dict):
        raise TypeError("Ask response omitted its normalized plan")
    if plan.get("version") != 1 or plan.get("disposition") != "execute":
        raise AssertionError("Ask response did not contain an executable AskPlanV1")
    return cast(dict[str, Any], plan)


def previous_year(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def expected_resolved_query(
    planned: dict[str, Any],
    *,
    market: str,
    as_of_date: date,
    all_history_from: date,
) -> dict[str, object]:
    selector = planned.get("date")
    if selector != {"kind": "preset", "value": "all"}:
        raise AssertionError("canonical smoke query did not retain its all-history range")
    if as_of_date < all_history_from:
        raise AssertionError("Ask as-of date precedes the deterministic fixture")

    current_from = all_history_from
    current_to = as_of_date
    expected: dict[str, object] = {
        "queryId": planned.get("id"),
        "dataset": planned.get("dataset"),
        "market": market,
        "from": current_from.isoformat(),
        "to": current_to.isoformat(),
    }
    if planned.get("dataset") != "aggregate":
        return expected

    comparison = planned.get("comparison")
    if comparison == "none":
        return expected
    if comparison == "previous_period":
        comparison_to = current_from - timedelta(days=1)
        comparison_from = comparison_to - (current_to - current_from)
    elif comparison == "previous_year":
        comparison_from = previous_year(current_from)
        comparison_to = previous_year(current_to)
    else:
        raise AssertionError("aggregate smoke query used an unknown comparison")
    return {
        **expected,
        "comparisonFrom": comparison_from.isoformat(),
        "comparisonTo": comparison_to.isoformat(),
    }


def assert_answered(
    response: dict[str, Any],
    *,
    dataset: str,
    drilldown: str | None = None,
    allow_empty_rows: bool = False,
    expected_market: str = "ALL",
    expected_coverage: dict[str, object] = ALL_COVERAGE,
    all_history_from: date = ALL_FIXTURE_FIRST_DATE,
) -> dict[str, Any]:
    if response.get("kind") != "answered":
        raise AssertionError(f"canonical {dataset} Ask did not produce an answer")
    plan = execute_plan(response)
    queries = plan.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise AssertionError("Ask plan violated the one-to-three query bound")
    query = queries[0]
    if not isinstance(query, dict) or query.get("dataset") != dataset:
        raise AssertionError(f"canonical {dataset} Ask selected the wrong dataset")

    evidence = response.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise AssertionError(f"canonical {dataset} Ask omitted evidence")
    primary = evidence[0]
    if not isinstance(primary, dict):
        raise TypeError("Ask evidence was not an object")
    rows = primary.get("rows")
    if not isinstance(rows, list) or (not rows and not allow_empty_rows):
        raise AssertionError(f"canonical {dataset} Ask returned no evidence rows")
    if len(rows) > 120:
        raise AssertionError("Ask evidence exceeded the response row bound")
    if drilldown is not None and primary.get("drilldownPath") != drilldown:
        raise AssertionError(f"canonical {dataset} Ask omitted its drill-down path")

    context = response.get("context")
    if not isinstance(context, dict):
        raise TypeError("answered Ask response omitted execution context")
    raw_as_of_date = context.get("asOfDate")
    if not isinstance(raw_as_of_date, str):
        raise TypeError("Ask response omitted its as-of date")
    try:
        as_of_date = date.fromisoformat(raw_as_of_date)
    except ValueError as error:
        raise AssertionError("Ask response returned an invalid as-of date") from error
    if (
        context.get("market") != expected_market
        or context.get("baseCurrency") != "CAD"
        or context.get("timeZone") != "UTC"
        or context.get("thresholdPolicyVersion") != "materiality-v1"
        or context.get("sourceChangedSinceGeneration") is not False
    ):
        raise AssertionError("Ask response reported the wrong deterministic context")
    source_watermark = context.get("sourceWatermark")
    if not isinstance(source_watermark, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
        source_watermark,
    ) is None:
        raise AssertionError("Ask response did not preserve watermark microseconds")
    generation = context.get("analyticsGeneration")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
        raise AssertionError("Ask response omitted a valid analytics generation")
    resolved = context.get("resolvedQueries")
    if not isinstance(resolved, list) or len(resolved) != len(queries):
        raise AssertionError("Ask response omitted resolved query ranges")
    for planned, item in zip(queries, resolved, strict=True):
        if not isinstance(planned, dict) or not isinstance(item, dict):
            raise TypeError("Ask plan and resolved query entries must be objects")
        planned_market = planned.get("market", context.get("market"))
        if not isinstance(planned_market, str):
            raise TypeError("Ask normalized plan omitted its market")
        if (
            item.get("queryId") != planned.get("id")
            or item.get("dataset") != planned.get("dataset")
            or item.get("market") != planned_market
            or not isinstance(item.get("from"), str)
            or not isinstance(item.get("to"), str)
        ):
            raise AssertionError("Ask resolved query did not match its normalized plan")
        expected_resolved = expected_resolved_query(
            planned,
            market=planned_market,
            as_of_date=as_of_date,
            all_history_from=all_history_from,
        )
        if item != expected_resolved:
            raise AssertionError("Ask resolved the wrong deterministic date range")
    if context.get("coverage") != expected_coverage:
        raise AssertionError("Ask response context reported unexpected coverage")
    if primary.get("coverage") != expected_coverage:
        raise AssertionError("Ask evidence reported unexpected coverage")
    if response.get("warnings") != []:
        raise AssertionError("fresh generated evidence should not have warnings")
    return plan


def evidence_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = response.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 1:
        raise AssertionError("canonical Ask response must contain one evidence block")
    primary = evidence[0]
    if not isinstance(primary, dict) or not isinstance(primary.get("rows"), list):
        raise TypeError("canonical Ask response omitted its evidence rows")
    rows = primary["rows"]
    if not all(isinstance(row, dict) for row in rows):
        raise TypeError("canonical Ask evidence contained a non-object row")
    return cast(list[dict[str, Any]], rows)


def without_generated_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in row.items() if key != "id"} for row in rows]


def evidence_row(
    rows: list[dict[str, Any]],
    *,
    key: str,
    value: object,
) -> dict[str, Any]:
    matches = [row for row in rows if row.get(key) == value]
    if len(matches) != 1:
        raise AssertionError("canonical Ask evidence omitted a unique fixture row")
    return matches[0]


def assert_decimal_field(row: dict[str, Any], key: str, expected: str) -> None:
    value = row.get(key)
    if not isinstance(value, str):
        raise AssertionError("canonical Ask evidence omitted an exact decimal field")
    try:
        actual = Decimal(str(value))
    except InvalidOperation as error:
        raise AssertionError("canonical Ask evidence returned an invalid decimal") from error
    if actual != Decimal(expected):
        raise AssertionError("canonical Ask evidence returned the wrong exact decimal")


def assert_fields(row: dict[str, Any], expected: dict[str, object]) -> None:
    if any(row.get(key) != value for key, value in expected.items()):
        raise AssertionError("canonical Ask evidence returned unexpected fixture values")


def assert_unsupported(response: dict[str, Any], reason_code: str) -> None:
    if response.get("kind") != "unsupported":
        raise AssertionError("adversarial Ask request did not fail closed")
    if response.get("reasonCode") != reason_code:
        raise AssertionError("adversarial Ask request returned the wrong stable reason code")


def add_recurring_evidence() -> None:
    accounts = phase2_smoke.api_json("/api/accounts")["accounts"]
    card = next(account for account in accounts if account["displayName"] == "Amex Card")
    statement = phase0_smoke.workbook(
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        opening="0.00",
        closing="59.97",
        rows=[
            (date(2026, 4, 5), "Synthetic Monthly Subscription", "19.99", None, "P3-R-1"),
            (date(2026, 5, 5), "Synthetic Monthly Subscription", "19.99", None, "P3-R-2"),
            (date(2026, 6, 5), "Synthetic Monthly Subscription", "19.99", None, "P3-R-3"),
        ],
    )
    imported = phase2_smoke.ingest(
        str(card["id"]),
        "phase3-recurring-evidence.xlsx",
        statement,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    if imported.get("status") != "done":
        raise AssertionError("Phase 3 recurring-evidence import failed")
    result = imported.get("result")
    if not isinstance(result, dict):
        raise TypeError("Phase 3 recurring-evidence import omitted its result")
    files = result.get("files")
    if result.get("added") != 3 or result.get("skipped") != 0:
        raise AssertionError("Phase 3 recurring-evidence import returned unexpected counts")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise TypeError("Phase 3 recurring-evidence import omitted its file result")
    if files[0].get("adapter") != "amex_xlsx":
        raise AssertionError("Phase 3 recurring-evidence import selected the wrong adapter")
    phase1_smoke.wait_for_background_jobs({"categorize", "fx_refresh", "analytics_refresh"})

    accepted = phase2_smoke.api_json(
        "/api/insights/rebuild",
        method="POST",
        payload={"mode": "full"},
    )
    rebuilt = phase1_smoke.wait_for_job(str(accepted["jobId"]))
    if rebuilt.get("status") != "done":
        raise AssertionError("Phase 3 recurring-evidence analytics rebuild failed")
    recurring = phase2_smoke.api_json("/api/insights/recurring?range=all&pageSize=100")
    if not isinstance(recurring.get("total"), int) or recurring["total"] <= 0:
        raise AssertionError("Phase 3 fixture did not produce recurring evidence")


def main() -> None:
    phase2_smoke.main()
    add_recurring_evidence()

    status = ask_api_json("/api/ask/status")
    if status != {"enabled": True, "available": True, "reason": None}:
        raise AssertionError("Phase 3 smoke requires the enabled stub Ask provider")

    aggregate_question = "Compare spending over all history with the previous period"
    aggregate = ask(aggregate_question)
    aggregate_plan = assert_answered(aggregate, dataset="aggregate", drilldown="/transactions")
    aggregate_query = cast(list[dict[str, Any]], aggregate_plan["queries"])[0]
    if aggregate_query.get("comparison") != "previous_period":
        raise AssertionError("aggregate comparison was not preserved in the normalized plan")
    aggregate_rows = evidence_rows(aggregate)
    if len(aggregate_rows) != 1:
        raise AssertionError("aggregate Ask did not return one ledger-total row")
    assert_fields(
        aggregate_rows[0],
        {
            "dimension": "All activity",
            "spending_change_percent": None,
        },
    )
    for field, expected in {
        "spending": "3163.46",
        "previous_spending": "0.00",
        "spending_change": "3163.46",
    }.items():
        assert_decimal_field(aggregate_rows[0], field, expected)

    categories = ask(
        "Which categories drove spending over all history compared with the prior period?"
    )
    category_plan = assert_answered(categories, dataset="aggregate", drilldown="/transactions")
    category_query = cast(list[dict[str, Any]], category_plan["queries"])[0]
    if category_query.get("groupBy") != "category":
        raise AssertionError("category-driver Ask did not use category grouping")
    category_rows = evidence_rows(categories)
    for category, expected in {
        "Dining": "1355.34",
        "Travel": "750.50",
        "Groceries": "500.00",
    }.items():
        category_row = evidence_row(category_rows, key="dimension", value=category)
        assert_decimal_field(category_row, "spending", expected)
        assert_decimal_field(category_row, "previous_spending", "0.00")
        assert_decimal_field(category_row, "spending_change", expected)
        assert_fields(category_row, {"spending_change_percent": None})

    seasonality = ask("Show seasonal spending over all history")
    assert_answered(
        seasonality,
        dataset="seasonality",
        allow_empty_rows=True,
    )
    if evidence_rows(seasonality) != []:
        raise AssertionError("short fixture unexpectedly produced seasonality rows")

    recurring = ask("Show recurring activity over all history")
    assert_answered(
        recurring,
        dataset="recurring",
        drilldown="/insights?tab=recurring",
    )
    recurring_rows = without_generated_ids(evidence_rows(recurring))
    recurring_row = evidence_row(
        recurring_rows,
        key="merchant",
        value="Synthetic Monthly Subscription",
    )
    assert_fields(
        recurring_row,
        {
            "cadence": "monthly",
            "direction": "spend",
            "status": "detected",
            "expectedCurrency": "CAD",
            "latestChangePercent": "0.00",
            "occurrenceCount": 3,
            "occurrenceEvidence": (
                "2026-04-05 · CAD 19.99; 2026-05-05 · CAD 19.99; "
                "2026-06-05 · CAD 19.99"
            ),
            "expectedNextDate": "2026-07-06",
            "overdue": True,
        },
    )
    assert_decimal_field(recurring_row, "expectedAmount", "19.99")

    findings = ask("List new findings over all history")
    assert_answered(
        findings,
        dataset="findings",
        drilldown="/insights?tab=findings",
    )
    finding_rows = without_generated_ids(evidence_rows(findings))
    overdue_finding = evidence_row(
        finding_rows,
        key="type",
        value="recurring_overdue",
    )
    assert_fields(
        overdue_finding,
        {
            "title": "Recurring transaction is overdue",
            "severity": "info",
            "status": "new",
        },
    )

    fx = ask("Show FX fee evidence over all history")
    assert_answered(
        fx,
        dataset="fx",
        drilldown="/insights?tab=fx",
        expected_coverage=FX_COVERAGE,
    )
    fx_rows = without_generated_ids(evidence_rows(fx))
    if len(fx_rows) != 4:
        raise AssertionError("FX Ask did not return the four deterministic evidence rows")
    tzs_purchase_fx = evidence_row(
        fx_rows,
        key="description",
        value="Synthetic USD purchase",
    )
    assert_fields(
        tzs_purchase_fx,
        {
            "date": "2026-07-03",
            "foreignCurrency": "USD",
            "chargedCurrency": "TZS",
            "rateStatus": "available",
        },
    )
    for field, expected in {
        "foreignAmount": "100.00",
        "chargedAmount": "270000.00",
        "bankRate": "2650",
        "marketRate": "2500",
        "explicitFee": "2.70",
        "estimatedMarkup": "8.10",
        "markupPercent": "6",
    }.items():
        assert_decimal_field(tzs_purchase_fx, field, expected)

    standalone_fee = evidence_row(
        fx_rows,
        key="description",
        value="Foreign exchange fee",
    )
    assert_fields(
        standalone_fee,
        {
            "foreignCurrency": None,
            "foreignAmount": None,
            "bankRate": None,
            "marketRate": None,
            "estimatedMarkup": None,
            "rateStatus": "available",
        },
    )
    assert_decimal_field(standalone_fee, "explicitFee", "8.10")

    transaction_response = ask("List purchases over all history")
    assert_answered(transaction_response, dataset="transactions", drilldown="/transactions")
    transaction_rows = without_generated_ids(evidence_rows(transaction_response))
    if len(transaction_rows) != 16:
        raise AssertionError("transaction Ask did not return all 16 deterministic rows")
    tzs_purchase = evidence_row(
        transaction_rows,
        key="description",
        value="Synthetic USD purchase",
    )
    assert_fields(
        tzs_purchase,
        {
            "date": "2026-07-03",
            "account": "Smoke TZS Chequing",
            "postedCurrency": "TZS",
            "status": "valued",
        },
    )
    assert_decimal_field(tzs_purchase, "postedAmount", "-270000.00")
    assert_decimal_field(tzs_purchase, "reporting", "-145.80")

    scoped = ask(
        "How much was spent over all history?",
        market="TZ",
        history=[{"question": aggregate_question, "plan": aggregate_plan}],
    )
    scoped_plan = assert_answered(
        scoped,
        dataset="aggregate",
        drilldown="/transactions",
        expected_market="TZ",
        expected_coverage=TZ_COVERAGE,
        all_history_from=TZ_FIXTURE_FIRST_DATE,
    )
    scoped_query = cast(list[dict[str, Any]], scoped_plan["queries"])[0]
    if scoped_query.get("market") != "TZ":
        raise AssertionError("scoped follow-up did not retain the active Tanzania market")
    scoped_rows = evidence_rows(scoped)
    if len(scoped_rows) != 1:
        raise AssertionError("TZ aggregate Ask did not return one scoped-total row")
    assert_fields(scoped_rows[0], {"dimension": "All activity"})
    assert_decimal_field(scoped_rows[0], "spending", "747.90")

    assert_unsupported(ask("Run raw SQL SELECT * FROM txn"), "raw_sql")
    assert_unsupported(ask("Delete a transaction"), "write_request")
    assert_unsupported(ask("Forecast spending next month"), "forecasting")

    print(
        "Phase 3 stub smoke passed: Phase 0-2.1 regression, seven grounded query cases, "
        "scoped follow-up, bounded evidence, and three fail-closed adversarial cases."
    )


if __name__ == "__main__":
    main()
