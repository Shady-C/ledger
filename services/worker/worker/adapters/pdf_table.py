"""Deterministic PDF table extraction with an explicit Phase 1 AI handoff."""

from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path

import pdfplumber

from worker.adapters.base import AdapterError
from worker.adapters.generic_csv import GenericCsvAdapter
from worker.models import AccountKind, ParsedFile, ParseResult, ParseStatus, StatementMetadata


class PdfTableAdapter:
    format = "pdf"
    name = "pdf_table"

    def detect(self, file: ParsedFile) -> float:
        if file.extension != ".pdf" and not file.content.startswith(b"%PDF"):
            return 0.0
        try:
            rows = self._extract_pdfplumber(file.content)
        except Exception:
            return 0.35
        if rows and GenericCsvAdapter._locate_header(rows) is not None:
            return 0.91
        return 0.45

    def parse(
        self,
        file: ParsedFile,
        *,
        account_kind: AccountKind = AccountKind.CREDIT_CARD,
    ) -> ParseResult:
        rows = self._extract_pdfplumber(file.content)
        if not rows:
            rows = self._extract_camelot(file.content)
        if not rows:
            return self._needs_ai("deterministic PDF extraction found no tables")
        try:
            parsed = GenericCsvAdapter().parse_tabular_rows(rows, account_kind=account_kind)
        except AdapterError as exc:
            return self._needs_ai(f"deterministic PDF table was not usable: {exc}")
        return parsed.model_copy(update={"adapter": self.name})

    @staticmethod
    def _extract_pdfplumber(content: bytes) -> list[list[object]]:
        rows: list[list[object]] = []
        with pdfplumber.open(BytesIO(content)) as document:
            for page in document.pages:
                for table in page.extract_tables() or []:
                    rows.extend([list(row) for row in table if row])
        return rows

    @staticmethod
    def _extract_camelot(content: bytes) -> list[list[object]]:
        try:
            import camelot
        except ImportError:
            return []
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(content)
                temporary_path = Path(handle.name)
            tables = camelot.read_pdf(  # type: ignore[attr-defined]
                str(temporary_path), pages="all", flavor="stream"
            )
            rows: list[list[object]] = []
            for table in tables:
                rows.extend(table.df.to_numpy().tolist())
            return rows
        except Exception:
            return []
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _needs_ai(self, reason: str) -> ParseResult:
        return ParseResult(
            adapter=self.name,
            status=ParseStatus.NEEDS_AI,
            statement=StatementMetadata(),
            reason=reason,
        )
