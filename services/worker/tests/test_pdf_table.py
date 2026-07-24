from __future__ import annotations

from decimal import Decimal

from worker.adapters.pdf_table import PdfTableAdapter
from worker.models import ParsedFile, ParseStatus


def test_parses_a_deterministically_extracted_pdf_table(monkeypatch) -> None:
    adapter = PdfTableAdapter()
    rows = [
        ["Statement Period", "2026-04-01 to 2026-04-30"],
        ["Opening Balance", "CAD 0.00"],
        ["Closing Balance", "CAD 4.50"],
        ["Date", "Description", "Amount", "Reference"],
        ["2026-04-05", "Synthetic Cafe", "4.50", "PDF-1"],
    ]
    monkeypatch.setattr(adapter, "_extract_pdfplumber", lambda _: rows)

    result = adapter.parse(ParsedFile(name="synthetic.pdf", content=b"%PDF synthetic"))

    assert result.adapter == "pdf_table"
    assert result.status is ParseStatus.READY
    assert result.rows[0].amount_native == Decimal("4.50")


def test_marks_irregular_pdf_as_needs_ai_without_calling_a_provider(monkeypatch) -> None:
    adapter = PdfTableAdapter()
    monkeypatch.setattr(adapter, "_extract_pdfplumber", lambda _: [])
    monkeypatch.setattr(adapter, "_extract_camelot", lambda _: [])

    result = adapter.parse(ParsedFile(name="irregular.pdf", content=b"%PDF synthetic"))

    assert result.status is ParseStatus.NEEDS_AI
    assert result.rows == ()
    assert "no tables" in (result.reason or "")
