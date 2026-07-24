"""Long-running PostgreSQL-backed worker process."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from worker.pipeline import IngestionPipeline, JobRunner
from worker.repository import PostgresRepository
from worker.storage import S3ObjectStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    base_currency: str
    poll_interval_seconds: float
    job_timeout_seconds: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("required environment variable DATABASE_URL is not set")
        base_currency = os.getenv("BASE_CURRENCY", "CAD").strip().upper()
        if len(base_currency) != 3 or not base_currency.isalpha():
            raise ValueError("BASE_CURRENCY must be a three-letter currency code")
        poll_interval = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))
        if poll_interval <= 0:
            raise ValueError("WORKER_POLL_INTERVAL_SECONDS must be positive")
        job_timeout = float(os.getenv("WORKER_JOB_TIMEOUT_SECONDS", "900"))
        if job_timeout <= 0:
            raise ValueError("WORKER_JOB_TIMEOUT_SECONDS must be positive")
        return cls(
            database_url=database_url,
            base_currency=base_currency,
            poll_interval_seconds=poll_interval,
            job_timeout_seconds=job_timeout,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("job_id", "adapter", "confidence", "file", "added", "skipped"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def run(settings: Settings, stop: threading.Event | None = None) -> None:
    stop_event = stop or threading.Event()
    repository = PostgresRepository(settings.database_url)
    pipeline = IngestionPipeline(
        store=S3ObjectStore.from_env(),
        repository=repository,
        base_currency=settings.base_currency,
    )
    runner = JobRunner(
        jobs=repository,
        pipeline=pipeline,
        timeout_seconds=settings.job_timeout_seconds,
    )
    LOGGER.info("worker started")
    while not stop_event.is_set():
        try:
            worked = runner.run_once()
        except Exception:
            # A transient DB/object-store outage must not terminate the container.
            LOGGER.exception("worker poll failed")
            worked = False
        if not worked:
            stop_event.wait(settings.poll_interval_seconds)
    LOGGER.info("worker stopped")


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("shutdown requested", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run(settings, stop)


if __name__ == "__main__":
    main()
