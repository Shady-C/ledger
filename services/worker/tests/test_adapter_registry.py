from __future__ import annotations

import pytest

from worker.models import ParsedFile
from worker.pipeline import AdapterRegistry, UnsupportedStatementError


def test_unknown_file_fails_before_any_ai_or_persistence() -> None:
    registry = AdapterRegistry()

    with pytest.raises(UnsupportedStatementError, match="no deterministic adapter"):
        registry.select(ParsedFile(name="unknown.bin", content=b"opaque"))
