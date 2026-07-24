from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

TransactionSpec = tuple[date, str, Decimal, str | None, str]


@pytest.fixture
def amex_workbook_bytes():
    def build(
        *,
        period_start: date,
        period_end: date,
        opening: Decimal,
        closing: Decimal,
        transactions: list[TransactionSpec],
    ) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Statement"
        sheet.append(["American Express - Synthetic Test Statement"])
        sheet.append([f"Statement Period: {period_start.isoformat()} to {period_end.isoformat()}"])
        sheet.append(["Account", "••••1001"])
        sheet.append(["Opening Balance", f"CAD {opening}"])
        sheet.append(["Closing Balance", f"CAD {closing}"])
        sheet.append([])
        sheet.append([])
        sheet.append(["Date", "Description", "Amount", "Foreign Spend Amount", "Reference"])
        for booked, description, amount, foreign, reference in transactions:
            sheet.append([booked, description, str(amount), foreign, reference])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        return output.getvalue()

    return build
