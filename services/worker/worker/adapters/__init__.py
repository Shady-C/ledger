"""Built-in deterministic statement adapters."""

from worker.adapters.amex_xlsx import AmexXlsxAdapter
from worker.adapters.generic_csv import GenericCsvAdapter
from worker.adapters.generic_xlsx import GenericXlsxAdapter
from worker.adapters.ofx import OfxAdapter
from worker.adapters.pdf_table import PdfTableAdapter

__all__ = [
    "AmexXlsxAdapter",
    "GenericCsvAdapter",
    "GenericXlsxAdapter",
    "OfxAdapter",
    "PdfTableAdapter",
]
