"""Built-in deterministic statement adapters."""

from worker.adapters.amex_xlsx import AmexXlsxAdapter
from worker.adapters.generic_csv import GenericCsvAdapter
from worker.adapters.generic_xlsx import GenericXlsxAdapter
from worker.adapters.im_bank_tz_pdf import ImBankTanzaniaPdfV1Adapter
from worker.adapters.ofx import OfxAdapter
from worker.adapters.pdf_table import PdfTableAdapter
from worker.adapters.wealthsimple_chequing_pdf import WealthsimpleChequingPdfV1Adapter

__all__ = [
    "AmexXlsxAdapter",
    "GenericCsvAdapter",
    "GenericXlsxAdapter",
    "ImBankTanzaniaPdfV1Adapter",
    "OfxAdapter",
    "PdfTableAdapter",
    "WealthsimpleChequingPdfV1Adapter",
]
