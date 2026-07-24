"""Exercise the Phase 2 stack with synthetic, non-private statements.

This is a synthetic integration contract, not institution-specific acceptance.
The supplied I&M Tanzania TZS PDFs have their own local acceptance command; a
named USD institution adapter is deferred under ADR-0006.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import phase0_smoke
import phase1_smoke


def api_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    return phase1_smoke.api_json(path, method=method, payload=payload)


def expect_api_error(
    path: str,
    *,
    method: str,
    payload: dict[str, object],
    status: int,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{phase0_smoke.BASE_URL}{path}",
        data=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "origin": phase0_smoke.BASE_URL,
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=phase0_smoke.HTTP_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        assert error.code == status, response_body
        return cast(dict[str, Any], json.loads(response_body))
    raise AssertionError(f"{method} {path} returned success instead of {status}: {response_body}")


def multipart(
    account_id: str,
    name: str,
    content: bytes,
    *,
    mime: str,
) -> tuple[bytes, str]:
    boundary = f"ledger-phase2-smoke-{uuid.uuid4().hex}"
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="accountId"\r\n\r\n',
        f"{account_id}\r\n".encode(),
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def ingest(
    account_id: str,
    name: str,
    content: bytes,
    *,
    mime: str,
) -> dict[str, Any]:
    body, content_type = multipart(account_id, name, content, mime=mime)
    accepted = phase0_smoke.json_request(
        "/api/ingest",
        method="POST",
        body=body,
        content_type=content_type,
    )
    return phase1_smoke.wait_for_job(str(accepted["jobId"]))


def tzs_original_usd_csv() -> bytes:
    return (
        b"Date,Description,Debit,Credit,Currency,Original Amount,"
        b"Original Currency,FX Fee,Reference\n"
        b"2026-07-03,Synthetic USD purchase,270000.00,,TZS,100.00,USD,5000.00,TZS-USD-1\n"
        b"2026-07-04,Foreign exchange fee,15000.00,,TZS,,,,TZS-FEE-1\n"
    )


def usd_original_tzs_csv() -> bytes:
    return (
        b"Date,Description,Debit,Credit,Currency,Original Amount,"
        b"Original Currency,FX Fee,Reference\n"
        b"2026-07-05,Synthetic TZS purchase,40.00,,USD,100000.00,TZS,,USD-TZS-1\n"
    )


def assert_import(
    job: dict[str, Any],
    *,
    adapter: str,
    added: int,
    skipped: int,
) -> None:
    assert job["status"] == "done", job
    assert job["result"]["added"] == added, job
    assert job["result"]["skipped"] == skipped, job
    file_result = job["result"]["files"][0]
    assert file_result["adapter"] == adapter, file_result
    assert file_result["reconciliation"]["status"] == "pending", file_result


def decimal(value: str | None) -> Decimal:
    assert value is not None
    return Decimal(value)


def transaction_by_description(items: list[dict[str, Any]], description: str) -> dict[str, Any]:
    return next(item for item in items if item["description"] == description)


def assert_three_layer_transactions(*, usd_account_id: str, tzs_account_id: str) -> None:
    usd_rows = api_json(
        f"/api/transactions?accountId={usd_account_id}&pageSize=100"
    )["items"]
    usd_purchase = transaction_by_description(usd_rows, "Synthetic TZS purchase")
    assert usd_purchase["originalAmount"] == "-100000.00"
    assert usd_purchase["originalCurrency"] == "TZS"
    assert usd_purchase["amountNative"] == "-40.00"
    assert usd_purchase["currencyNative"] == "USD"
    assert usd_purchase["amountBase"] == "-54.00"
    assert usd_purchase["currencyBase"] == "CAD"
    assert usd_purchase["valuationStatus"] == "valued"
    assert usd_purchase["fxFeeAmountNative"] is None
    assert usd_purchase["isFxFee"] is False

    tzs_rows = api_json(
        f"/api/transactions?accountId={tzs_account_id}&pageSize=100"
    )["items"]
    tzs_purchase = transaction_by_description(tzs_rows, "Synthetic USD purchase")
    assert tzs_purchase["originalAmount"] == "-100.00"
    assert tzs_purchase["originalCurrency"] == "USD"
    assert tzs_purchase["amountNative"] == "-270000.00"
    assert tzs_purchase["currencyNative"] == "TZS"
    assert tzs_purchase["amountBase"] == "-145.80"
    assert tzs_purchase["currencyBase"] == "CAD"
    assert tzs_purchase["valuationStatus"] == "valued"
    assert tzs_purchase["fxFeeAmountNative"] == "5000.00"
    assert tzs_purchase["isFxFee"] is False

    standalone = transaction_by_description(tzs_rows, "Foreign exchange fee")
    assert standalone["originalAmount"] is None
    assert standalone["originalCurrency"] is None
    assert standalone["amountNative"] == "-15000.00"
    assert standalone["amountBase"] == "-8.10"
    assert standalone["valuationStatus"] == "valued"
    assert standalone["fxFeeAmountNative"] is None
    assert standalone["isFxFee"] is True


def assert_fx_analytics() -> None:
    fx = api_json("/api/analytics/fx")
    assert fx["baseCurrency"] == "CAD"
    assert fx["status"] == "complete", fx
    assert fx["missingRateCount"] == 0, fx

    hotel = transaction_by_description(fx["transactions"], "Synthetic Hotel")
    assert decimal(hotel["marketRate"]) == Decimal("1.35")
    assert decimal(hotel["estimatedMarkupNative"]) == Decimal("48.50")
    assert decimal(hotel["estimatedMarkupBase"]) == Decimal("48.50")
    assert decimal(hotel["explicitFeeNative"]) == Decimal(0)
    assert hotel["isStandaloneFee"] is False

    tzs_purchase = transaction_by_description(fx["transactions"], "Synthetic USD purchase")
    assert decimal(tzs_purchase["bankAppliedRate"]) == Decimal(2650)
    assert decimal(tzs_purchase["marketRate"]) == Decimal(2500)
    assert decimal(tzs_purchase["markupPercent"]) == Decimal(6)
    assert decimal(tzs_purchase["explicitFeeNative"]) == Decimal(5000)
    assert decimal(tzs_purchase["explicitFeeBase"]) == Decimal("2.70")
    assert decimal(tzs_purchase["estimatedMarkupNative"]) == Decimal(15000)
    assert decimal(tzs_purchase["estimatedMarkupBase"]) == Decimal("8.10")
    assert tzs_purchase["isStandaloneFee"] is False

    standalone = transaction_by_description(fx["transactions"], "Foreign exchange fee")
    assert standalone["foreignAmount"] is None
    assert standalone["foreignCurrency"] is None
    assert standalone["bankAppliedRate"] is None
    assert decimal(standalone["explicitFeeNative"]) == Decimal(15000)
    assert decimal(standalone["explicitFeeBase"]) == Decimal("8.10")
    assert standalone["estimatedMarkupNative"] is None
    assert standalone["isStandaloneFee"] is True

    usd_purchase = transaction_by_description(fx["transactions"], "Synthetic TZS purchase")
    assert decimal(usd_purchase["bankAppliedRate"]) == Decimal("0.0004")
    assert decimal(usd_purchase["marketRate"]) == Decimal("0.0004")
    assert decimal(usd_purchase["estimatedMarkupNative"]) == Decimal(0)
    assert decimal(usd_purchase["estimatedMarkupBase"]) == Decimal(0)


def assert_insights() -> None:
    accepted = api_json(
        "/api/insights/rebuild",
        method="POST",
        payload={"mode": "full"},
    )
    assert accepted["kind"] == "analytics_refresh", accepted
    rebuilt = phase1_smoke.wait_for_job(str(accepted["jobId"]))
    assert rebuilt["status"] == "done", rebuilt
    assert rebuilt["result"]["mode"] == "full", rebuilt
    assert rebuilt["result"]["generation"] > 0, rebuilt
    assert rebuilt["result"]["aggregateCount"] > 0, rebuilt
    assert rebuilt["result"]["durationMs"] >= 0, rebuilt

    summary = api_json("/api/insights/summary?range=all")
    assert summary["baseCurrency"] == "CAD"
    assert summary["coverage"]["status"] == "complete", summary
    assert summary["latestRun"]["status"] == "succeeded", summary
    assert summary["latestRun"]["mode"] == "full", summary

    trends = api_json("/api/insights/trends?range=all&groupBy=ledger")
    assert trends["baseCurrency"] == "CAD"
    assert trends["groupBy"] == "ledger"
    assert trends["points"], trends

    seasonality = api_json("/api/insights/seasonality?range=all")
    assert seasonality["baseCurrency"] == "CAD"
    assert seasonality["status"] == "insufficient_history", seasonality
    assert seasonality["requiredHistoryMonths"] == 12

    recurring = api_json("/api/insights/recurring?range=all&pageSize=100")
    assert recurring["baseCurrency"] == "CAD"
    assert recurring["page"] == 1

    settings = api_json("/api/insights/settings")
    assert settings["settings"]["sensitivity"] == "balanced"

    findings = api_json("/api/insights/findings?range=all&pageSize=100")
    assert findings["total"] > 0, findings
    finding = next(item for item in findings["findings"] if item["status"] == "new")
    reviewed = api_json(
        f"/api/insights/findings/{finding['id']}",
        method="PATCH",
        payload={"status": "confirmed"},
    )["finding"]
    assert reviewed["status"] == "confirmed", reviewed
    assert reviewed["reviewedAt"] is not None, reviewed

    confirmed = api_json(
        "/api/insights/findings?range=all&status=confirmed&pageSize=100"
    )["findings"]
    assert any(item["id"] == finding["id"] for item in confirmed)


def main() -> None:
    # Retain the permanent Phase 0/1 reconciliation and repeat-ingestion gate.
    phase0_smoke.main()

    fixed = expect_api_error(
        "/api/settings/base-currency",
        method="POST",
        payload={"baseCurrency": "USD"},
        status=409,
    )
    assert fixed["error"]["code"] == "base_currency_fixed", fixed
    assert api_json("/api/settings")["baseCurrency"] == "CAD"

    institution = api_json(
        "/api/institutions",
        method="POST",
        payload={"name": "Synthetic Phase 2 Smoke Bank"},
    )["institution"]
    usd_account = phase1_smoke.create_account(
        institution_id=institution["id"],
        name="Smoke USD Chequing",
        kind="chequing",
        currency="USD",
        masked="••••5678",
    )
    tzs_account = phase1_smoke.create_account(
        institution_id=institution["id"],
        name="Smoke TZS Chequing",
        kind="chequing",
        currency="TZS",
        masked="••••2468",
    )

    fixtures = [
        (
            usd_account["id"],
            "smoke-us-bank.ofx",
            phase1_smoke.ofx2_bank_usd(),
            "application/x-ofx",
            "ofx_qfx",
            2,
        ),
        (
            tzs_account["id"],
            "smoke-tzs-bank.ofx",
            phase1_smoke.ofx1_bank_tzs(),
            "application/x-ofx",
            "ofx_qfx",
            2,
        ),
        (
            usd_account["id"],
            "smoke-usd-original-tzs.csv",
            usd_original_tzs_csv(),
            "text/csv",
            "generic_csv",
            1,
        ),
        (
            tzs_account["id"],
            "smoke-tzs-original-usd.csv",
            tzs_original_usd_csv(),
            "text/csv",
            "generic_csv",
            2,
        ),
    ]
    for account_id, name, content, mime, adapter, added in fixtures:
        assert_import(
            ingest(account_id, name, content, mime=mime),
            adapter=adapter,
            added=added,
            skipped=0,
        )
    for account_id, name, content, mime, adapter, added in fixtures:
        assert_import(
            ingest(account_id, name, content, mime=mime),
            adapter=adapter,
            added=0,
            skipped=added,
        )

    phase1_smoke.wait_for_background_jobs({"categorize", "fx_refresh", "analytics_refresh"})

    accounts = api_json("/api/accounts")["accounts"]
    seeded_card = next(account for account in accounts if account["displayName"] == "Amex Card")
    assert decimal(seeded_card["currentBalance"]) == Decimal("2855.59")
    assert api_json("/api/settings")["baseCurrency"] == "CAD"

    assert_three_layer_transactions(
        usd_account_id=usd_account["id"],
        tzs_account_id=tzs_account["id"],
    )
    assert_fx_analytics()
    assert_insights()

    assert {
        item["currencyBase"]
        for item in api_json("/api/transactions?pageSize=100")["items"]
    } == {"CAD"}

    print(
        "Phase 2 synthetic smoke passed: golden 2855.59, zero-row repeats, "
        "USD/TZS accounts, three-layer money, fixed CAD, FX evidence, analytics refresh, "
        "and Insights review. I&M Tanzania TZS acceptance is verified separately."
    )


if __name__ == "__main__":
    main()
