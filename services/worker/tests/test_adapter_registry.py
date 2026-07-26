from __future__ import annotations

import pytest

from worker.models import ParsedFile
from worker.pipeline import AdapterRegistry, UnsupportedStatementError


def test_unknown_file_fails_before_any_ai_or_persistence() -> None:
    registry = AdapterRegistry()

    with pytest.raises(UnsupportedStatementError, match="no deterministic adapter"):
        registry.select(ParsedFile(name="unknown.bin", content=b"opaque"))


def test_versioned_wealthsimple_adapter_precedes_the_generic_pdf_fallback() -> None:
    names = [adapter.name for adapter in AdapterRegistry().adapters]

    assert names.index("wealthsimple_chequing_pdf_v1") < names.index("im_bank_tz_pdf_v1")
    assert names.index("wealthsimple_chequing_pdf_v1") < names.index("pdf_table")
