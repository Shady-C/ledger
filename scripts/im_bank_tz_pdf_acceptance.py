"""Validate the supplied sanitized I&M Tanzania PDF layout without exposing rows."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from worker.adapters.im_bank_tz_pdf import ImBankTanzaniaPdfV1Adapter
from worker.models import AccountKind, ParsedFile
from worker.pipeline import IngestionPipeline
from worker.reconcile import reconcile_statement
from worker.repository import InMemoryRepository
from worker.storage import MemoryObjectStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIRECTORY = REPOSITORY_ROOT / "output" / "pdf"


@dataclass(frozen=True, slots=True)
class AcceptanceSummary:
    adapter: str
    statement_count: int
    reconciled_statement_count: int
    zero_activity_statement_count: int
    transaction_count: int
    repeated_statement_transaction_count: int
    repeat_added: int
    repeat_skipped: int
    native_currency: str
    reporting_status: str


def run(fixture_directory: Path) -> AcceptanceSummary:
    if not fixture_directory.is_dir():
        raise ValueError(f"fixture directory does not exist: {fixture_directory}")
    paths = tuple(sorted(fixture_directory.glob("*.pdf")))
    if not paths:
        raise ValueError(f"no PDF fixtures found in {fixture_directory}")

    adapter = ImBankTanzaniaPdfV1Adapter()
    parsed: list[tuple[Path, bytes, int]] = []
    zero_activity_count = 0
    transaction_count = 0
    for path in paths:
        content = path.read_bytes()
        source = ParsedFile(name=path.name, content=content)
        if adapter.detect(source) != 0.99:
            raise AssertionError(f"{path.name} did not match im_bank_tz_pdf_v1")
        result = adapter.parse(source, account_kind=AccountKind.CHEQUING)
        reconciliation = reconcile_statement(result.statement, result.rows)
        if reconciliation.status != "ok" or reconciliation.difference != 0:
            raise AssertionError(f"{path.name} did not reconcile exactly")
        if result.statement.currency != "TZS":
            raise AssertionError(f"{path.name} was not recognized as TZS")
        row_count = len(result.rows)
        parsed.append((path, content, row_count))
        zero_activity_count += int(row_count == 0)
        transaction_count += row_count

    repeat_path, repeat_content, repeat_count = max(parsed, key=lambda item: item[2])
    if repeat_count == 0:
        raise AssertionError("at least one supplied statement must contain transactions")
    key = f"statements/{repeat_path.name}"
    repository = InMemoryRepository(
        account_kinds={"tzs-account": AccountKind.CHEQUING},
        account_currencies={"tzs-account": "TZS"},
    )
    pipeline = IngestionPipeline(
        store=MemoryObjectStore({key: repeat_content}),
        repository=repository,
        auto_enqueue_fx_refresh=False,
        auto_enqueue_analytics=False,
    )
    first = pipeline.process_file(account_id="tzs-account", file_key=key)
    second = pipeline.process_file(account_id="tzs-account", file_key=key)
    if first.added != repeat_count or first.reconcile is None:
        raise AssertionError("first real-PDF ingestion did not persist every parsed row")
    if first.reconcile.get("status") != "ok":
        raise AssertionError("first real-PDF ingestion did not reconcile")
    if second.added != 0 or second.skipped != repeat_count:
        raise AssertionError("repeat real-PDF ingestion was not idempotent")
    if any(row.amount_base is not None for row in repository.transactions.values()):
        raise AssertionError("missing CAD rates must leave real TZS rows pending")

    return AcceptanceSummary(
        adapter="im_bank_tz_pdf_v1",
        statement_count=len(paths),
        reconciled_statement_count=len(paths),
        zero_activity_statement_count=zero_activity_count,
        transaction_count=transaction_count,
        repeated_statement_transaction_count=repeat_count,
        repeat_added=second.added,
        repeat_skipped=second.skipped,
        native_currency="TZS",
        reporting_status="pending_fx",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-directory",
        type=Path,
        default=Path(
            os.getenv("LEDGER_IM_BANK_TZ_FIXTURE_DIRECTORY", DEFAULT_FIXTURE_DIRECTORY)
        ),
    )
    args = parser.parse_args()
    print(json.dumps(asdict(run(args.fixture_directory.resolve())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
