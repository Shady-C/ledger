"""Exercise the complete Phase 1 stack with synthetic, non-private statements."""

from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Any, cast

import phase0_smoke

JOB_TIMEOUT_SECONDS = 120


def api_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    return phase0_smoke.json_request(
        path,
        method=method,
        body=body,
        content_type="application/json" if body is not None else None,
    )


def wait_for_job(job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        job = api_json(f"/api/jobs/{job_id}")
        if job["status"] in {"done", "failed", "needs_ai"}:
            return job
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish within {JOB_TIMEOUT_SECONDS} seconds")


def multipart(account_id: str, name: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"ledger-phase1-smoke-{uuid.uuid4().hex}"
    mime = "application/x-ofx"
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


def ingest(account_id: str, name: str, content: bytes) -> dict[str, Any]:
    body, content_type = multipart(account_id, name, content)
    accepted = phase0_smoke.json_request(
        "/api/ingest",
        method="POST",
        body=body,
        content_type=content_type,
    )
    return wait_for_job(str(accepted["jobId"]))


def ofx1_card() -> bytes:
    return b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS>
<CURDEF>USD</CURDEF><CCACCTFROM><ACCTID>99994242</ACCTID></CCACCTFROM>
<BANKTRANLIST><DTSTART>20260401000000<DTEND>20260430000000
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260405000000<TRNAMT>-100.00
<FITID>USC-1<NAME>ORBITAL SUPPLY 9876</STMTTRN>
<STMTTRN><TRNTYPE>PAYMENT<DTPOSTED>20260420000000<TRNAMT>25.00
<FITID>USC-2<NAME>PAYMENT THANK YOU</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>-75.00<DTASOF>20260430000000</LEDGERBAL>
</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""


def ofx2_bank_usd() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD</CURDEF><BANKACCTFROM><BANKID>001</BANKID><ACCTID>12345678</ACCTID></BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260501000000</DTSTART><DTEND>20260531000000</DTEND>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260503000000</DTPOSTED>
<TRNAMT>1000.00</TRNAMT><FITID>USB-1</FITID><NAME>FIXTURE PAYROLL</NAME>
</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260518000000</DTPOSTED>
<TRNAMT>-200.00</TRNAMT><FITID>USB-2</FITID><NAME>ZEPHYR GOODS 4321</NAME>
</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>800.00</BALAMT><DTASOF>20260531000000</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


def ofx1_bank_tzs() -> bytes:
    return b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>TZS</CURDEF><BANKACCTFROM><BANKID>255</BANKID><ACCTID>77772468</ACCTID></BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260601000000<DTEND>20260630000000
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260603000000<TRNAMT>2000000.00
<FITID>TZW-1<NAME>FIXTURE SALARY</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260621000000<TRNAMT>-500000.00
<FITID>TZW-2<NAME>KILIMANJARO BOOKS 2468</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>1500000.00<DTASOF>20260630000000</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


def create_account(
    *,
    institution_id: str,
    name: str,
    kind: str,
    currency: str,
    market_code: str,
    masked: str,
    credit_limit: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "institutionId": institution_id,
        "displayName": name,
        "kind": kind,
        "nativeCurrency": currency,
        "marketCode": market_code,
        "accountRefMasked": masked,
        "creditLimit": credit_limit,
    }
    return cast(
        dict[str, Any],
        api_json("/api/accounts", method="POST", payload=payload)["account"],
    )


def wait_for_background_jobs(required_kinds: set[str]) -> None:
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        jobs = api_json("/api/jobs?pageSize=100")["jobs"]
        background = [job for job in jobs if job["kind"] in required_kinds]
        active = [job for job in background if job["status"] in {"queued", "claimed"}]
        failed = [job for job in background if job["status"] == "failed"]
        if failed:
            raise AssertionError(f"background Phase 1 job failed: {failed}")
        completed_kinds = {job["kind"] for job in background if job["status"] == "done"}
        if not active and required_kinds <= completed_kinds:
            return
        time.sleep(0.25)
    raise AssertionError(f"background jobs did not settle: {sorted(required_kinds)}")


def exact(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def assert_ofx_import(job: dict[str, Any], *, added: int, skipped: int) -> None:
    assert job["status"] == "done", job
    assert job["result"]["added"] == added
    assert job["result"]["skipped"] == skipped
    result = job["result"]["files"][0]
    assert result["adapter"] == "ofx_qfx"
    assert result["reconciliation"]["status"] == "pending"


def switch_base_currency(target: str) -> None:
    previous_base = str(api_json("/api/settings")["baseCurrency"])
    before = api_json("/api/transactions?pageSize=100")["items"]
    native_truth = {
        item["id"]: (item["amountNative"], item["currencyNative"]) for item in before
    }
    accepted = api_json(
        "/api/settings/base-currency",
        method="POST",
        payload={"baseCurrency": target, "confirmed": True},
    )
    job_id = str(accepted["jobId"])
    observed_bases: set[str] = set()
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    terminal: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        rows = api_json("/api/transactions?pageSize=100")["items"]
        currencies = {item["currencyBase"] for item in rows}
        assert len(currencies) == 1, f"mixed-base read observed: {currencies}"
        observed_bases.update(currencies)
        job = api_json(f"/api/jobs/{job_id}")
        if job["status"] in {"done", "failed"}:
            terminal = job
            break
        time.sleep(0.05)
    assert terminal is not None, "base-currency rebuild did not finish"
    assert terminal["status"] == "done", terminal
    assert terminal["result"]["targetBaseCurrency"] == target

    after = api_json("/api/transactions?pageSize=100")["items"]
    assert {item["currencyBase"] for item in after} == {target}
    assert {
        item["id"]: (item["amountNative"], item["currencyNative"]) for item in after
    } == native_truth
    assert observed_bases <= {previous_base, target}
    assert api_json("/api/settings")["baseCurrency"] == target


def main() -> None:
    phase0_smoke.main()

    accounts = api_json("/api/accounts")["accounts"]
    seeded_card = next(account for account in accounts if account["displayName"] == "Amex Card")
    api_json(
        f"/api/accounts/{seeded_card['id']}",
        method="PATCH",
        payload={"creditLimit": "5000.00"},
    )

    institution = api_json(
        "/api/institutions",
        method="POST",
        payload={"name": "Synthetic Smoke Bank"},
    )["institution"]
    usd_card = create_account(
        institution_id=institution["id"],
        name="Smoke USD Card",
        kind="credit_card",
        currency="USD",
        market_code="CA",
        masked="••••4242",
        credit_limit="2000.00",
    )
    usd_bank = create_account(
        institution_id=institution["id"],
        name="Smoke USD Chequing",
        kind="chequing",
        currency="USD",
        market_code="CA",
        masked="••••5678",
    )
    tzs_wallet = create_account(
        institution_id=institution["id"],
        name="Smoke TZS Wallet",
        kind="wallet",
        currency="TZS",
        market_code="TZ",
        masked="••••2468",
    )

    fixtures = [
        (usd_card, "smoke-us-card.qfx", ofx1_card()),
        (usd_bank, "smoke-us-bank.ofx", ofx2_bank_usd()),
        (tzs_wallet, "smoke-tzs-wallet.ofx", ofx1_bank_tzs()),
    ]
    for account, name, content in fixtures:
        assert_ofx_import(ingest(account["id"], name, content), added=2, skipped=0)
    for account, name, content in fixtures:
        assert_ofx_import(ingest(account["id"], name, content), added=0, skipped=2)

    wait_for_background_jobs({"categorize", "fx_refresh"})

    categorized = api_json("/api/transactions?search=ORBITAL&pageSize=100")
    assert categorized["total"] == 1
    assert categorized["items"][0]["categorySource"] == "ai"
    assert categorized["items"][0]["categoryConfidence"] == "0.9900"

    account_response = api_json("/api/accounts")
    cards = {account["displayName"]: account for account in account_response["accounts"]}
    assert exact(cards["Amex Card"]["usedCredit"]) == Decimal("2855.59")
    assert exact(cards["Amex Card"]["availableCredit"]) == Decimal("2144.41")
    assert exact(cards["Smoke USD Card"]["usedCredit"]) == Decimal("75.00")
    utilization = account_response["creditUtilization"]
    assert utilization["baseCurrency"] == "CAD"
    assert exact(utilization["usedCreditBase"]) == Decimal("2956.84")
    assert exact(utilization["creditLimitBase"]) == Decimal("7700.00")
    assert exact(utilization["availableCreditBase"]) == Decimal("4743.16")
    assert exact(utilization["utilizationPercent"]) == Decimal("38.40")

    worth = api_json("/api/analytics/net-worth")
    assert worth["status"] == "complete", worth
    assert worth["baseCurrency"] == "CAD"
    assert exact(worth["assets"]) == Decimal("1890.00")
    assert exact(worth["liabilities"]) == Decimal("2956.84")
    assert exact(worth["netWorth"]) == Decimal("-1066.84")

    fx = api_json("/api/analytics/fx")
    hotel = next(item for item in fx["transactions"] if item["description"] == "Synthetic Hotel")
    assert exact(hotel["marketRate"]) == Decimal("1.35")
    assert exact(hotel["estimatedFeeNative"]) == Decimal("48.50")
    assert exact(hotel["estimatedFeeBase"]) == Decimal("48.50")

    switch_base_currency("TZS")
    worth_tzs = api_json("/api/analytics/net-worth")
    assert worth_tzs["status"] == "complete", worth_tzs
    assert worth_tzs["baseCurrency"] == "TZS"
    assert exact(worth_tzs["assets"]) == Decimal("3500000.00")
    assert exact(worth_tzs["liabilities"]) == Decimal("5475629.63")
    assert exact(worth_tzs["netWorth"]) == Decimal("-1975629.63")
    switch_base_currency("CAD")

    print(
        "Phase 1 smoke passed: golden 2855.59, OFX1/OFX2/QFX, USD/TZS FX, "
        "AI categorization, utilization/net worth, repeat idempotency, and CAD/TZS round trip."
    )


if __name__ == "__main__":
    main()
