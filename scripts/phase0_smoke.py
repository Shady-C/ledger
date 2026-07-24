"""Exercise the complete Phase 0 stack with three sanitized Amex workbooks."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from openpyxl import Workbook

BASE_URL = os.getenv("LEDGER_SMOKE_URL", "http://localhost:3000").rstrip("/")
HTTP_TIMEOUT_SECONDS = 10
JOB_TIMEOUT_SECONDS = 120


def workbook(
    *,
    period_start: date,
    period_end: date,
    opening: str,
    closing: str,
    rows: list[tuple[date, str, str, str | None, str]],
) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Statement"
    sheet.append(["American Express - Synthetic Smoke Statement"])
    sheet.append([f"Statement Period: {period_start.isoformat()} to {period_end.isoformat()}"])
    sheet.append(["Account", "••••1001"])
    sheet.append(["Opening Balance", f"CAD {opening}"])
    sheet.append(["Closing Balance", f"CAD {closing}"])
    sheet.append([])
    sheet.append([])
    sheet.append(["Date", "Description", "Amount", "Foreign Spend Amount", "Reference"])
    for booked, description, amount, foreign, reference in rows:
        sheet.append([booked, description, amount, foreign, reference])
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def golden_files() -> list[tuple[str, bytes]]:
    return [
        (
            "synthetic-01.xlsx",
            workbook(
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                opening="1000.00",
                closing="1200.00",
                rows=[
                    (date(2026, 1, 3), "Synthetic Grocery Market", "500.00", None, "G-1"),
                    (date(2026, 1, 25), "Payment Thank You", "-300.00", None, "G-2"),
                ],
            ),
        ),
        (
            "synthetic-02.xlsx",
            workbook(
                period_start=date(2026, 2, 1),
                period_end=date(2026, 2, 28),
                opening="1200.00",
                closing="1700.25",
                rows=[
                    (date(2026, 2, 8), "Synthetic Hotel", "750.50", "USD 520.00", "G-3"),
                    (date(2026, 2, 20), "Merchant Refund", "-250.25", None, "G-4"),
                ],
            ),
        ),
        (
            "synthetic-03.xlsx",
            workbook(
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
                opening="1700.25",
                closing="2855.59",
                rows=[
                    (date(2026, 3, 9), "Synthetic Coffee Cafe", "1355.34", None, "G-5"),
                    (date(2026, 3, 27), "Autopay Payment", "-200.00", None, "G-6"),
                ],
            ),
        ),
    ]


def json_request(
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if content_type:
        headers["content-type"] = content_type
    if method != "GET":
        # SvelteKit's CSRF guard expects browser-style form submissions to carry
        # a same-origin Origin header. The smoke client should exercise that path.
        headers["origin"] = BASE_URL
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned {error.code}: {detail}") from error
    return json.loads(payload)


def multipart(account_id: str, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = f"ledger-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def append(value: str) -> None:
        chunks.append(value.encode("utf-8"))

    append(f"--{boundary}\r\n")
    append('Content-Disposition: form-data; name="accountId"\r\n\r\n')
    append(f"{account_id}\r\n")
    for name, content in files:
        append(f"--{boundary}\r\n")
        append(f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n')
        append(
            "Content-Type: "
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
        )
        chunks.append(content)
        append("\r\n")
    append(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def ingest(account_id: str, files: list[tuple[str, bytes]]) -> dict[str, Any]:
    body, content_type = multipart(account_id, files)
    accepted = json_request("/api/ingest", method="POST", body=body, content_type=content_type)
    job_id = accepted["jobId"]
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        job = json_request(f"/api/jobs/{job_id}")
        if job["status"] in {"done", "failed", "needs_ai"}:
            return job
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish within {JOB_TIMEOUT_SECONDS} seconds")


def exact(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def main() -> None:
    health = json_request("/api/health")
    assert health == {"status": "ready"}

    accounts = json_request("/api/accounts")["accounts"]
    assert len(accounts) == 1, "smoke test requires a fresh Phase 0 database"
    account_id = accounts[0]["id"]
    files = golden_files()

    first = ingest(account_id, files)
    assert first["status"] == "done", first
    assert first["result"]["added"] == 6
    assert first["result"]["skipped"] == 0
    reconciliations = [item["reconciliation"] for item in first["result"]["files"]]
    assert [item["status"] for item in reconciliations] == ["ok", "ok", "ok"]
    assert exact(reconciliations[-1]["reportedClosing"]) == Decimal("2855.59")
    assert exact(reconciliations[-1]["calculatedClosing"]) == Decimal("2855.59")

    balance = json_request(f"/api/analytics/balance?accountId={account_id}")
    assert exact(balance["points"][-1]["balance"]) == Decimal("2855.59")
    cashflow = json_request(f"/api/analytics/cashflow?accountId={account_id}")
    assert [
        (
            point["period"],
            exact(point["inflow"]),
            exact(point["outflow"]),
            exact(point["net"]),
        )
        for point in cashflow["points"]
    ] == [
        ("2026-01-01", Decimal("0.00"), Decimal("500.00"), Decimal("-500.00")),
        ("2026-02-01", Decimal("250.25"), Decimal("750.50"), Decimal("-500.25")),
        ("2026-03-01", Decimal("0.00"), Decimal("1355.34"), Decimal("-1355.34")),
    ]
    transactions = json_request(f"/api/transactions?accountId={account_id}&pageSize=100")
    assert transactions["total"] == 6

    repeated = ingest(account_id, files)
    assert repeated["status"] == "done", repeated
    assert repeated["result"]["added"] == 0
    assert repeated["result"]["skipped"] == 6
    after_repeat = json_request(f"/api/transactions?accountId={account_id}&pageSize=100")
    assert after_repeat["total"] == 6

    print("Phase 0 smoke passed: closing 2855.59, 6 rows, repeat upload added 0.")


if __name__ == "__main__":
    main()
