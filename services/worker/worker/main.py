"""Long-running PostgreSQL-backed worker process."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from worker.ai_categorization import AICategorizationService
from worker.analytics import AnalyticsRefreshService, PostgresAnalyticsRepository
from worker.column_mapping import AIColumnMappingService
from worker.fx import (
    BaseCurrencyRebuildService,
    CachedFXRateProvider,
    FixtureFXRateProvider,
    FrankfurterFXRateProvider,
    FXRefreshService,
    PostgresFXRateCache,
)
from worker.llm.anthropic import AnthropicProvider
from worker.llm.fixture import FixtureLLMProvider
from worker.llm.provider import DisabledLLMProvider, LLMProvider
from worker.pipeline import IngestionPipeline, JobRunner
from worker.repository import PostgresRepository
from worker.storage import S3ObjectStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    poll_interval_seconds: float
    job_timeout_seconds: float
    provider_mode: str
    fx_max_staleness_days: int
    ai_category_auto_apply_threshold: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("required environment variable DATABASE_URL is not set")
        poll_interval = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))
        if poll_interval <= 0:
            raise ValueError("WORKER_POLL_INTERVAL_SECONDS must be positive")
        job_timeout = float(os.getenv("WORKER_JOB_TIMEOUT_SECONDS", "900"))
        if job_timeout <= 0:
            raise ValueError("WORKER_JOB_TIMEOUT_SECONDS must be positive")
        provider_mode = os.getenv("WORKER_PROVIDER_MODE", "live").strip().lower()
        if provider_mode not in {"live", "stub"}:
            raise ValueError("WORKER_PROVIDER_MODE must be live or stub")
        max_staleness = int(os.getenv("FX_MAX_STALENESS_DAYS", "7"))
        if not 0 <= max_staleness <= 7:
            raise ValueError("FX_MAX_STALENESS_DAYS must be between 0 and 7")
        auto_apply = float(os.getenv("AI_CATEGORY_AUTO_APPLY_THRESHOLD", "0.85"))
        if not 0 <= auto_apply <= 1:
            raise ValueError("AI_CATEGORY_AUTO_APPLY_THRESHOLD must be between 0 and 1")
        return cls(
            database_url=database_url,
            poll_interval_seconds=poll_interval,
            job_timeout_seconds=job_timeout,
            provider_mode=provider_mode,
            fx_max_staleness_days=max_staleness,
            ai_category_auto_apply_threshold=auto_apply,
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
    fx_upstream = (
        FixtureFXRateProvider()
        if settings.provider_mode == "stub"
        else FrankfurterFXRateProvider(max_staleness_days=settings.fx_max_staleness_days)
    )
    fx_provider = CachedFXRateProvider(
        cache=PostgresFXRateCache(
            settings.database_url,
            max_staleness_days=settings.fx_max_staleness_days,
        ),
        upstream=fx_upstream,
    )
    llm_provider: LLMProvider
    if settings.provider_mode == "stub":
        llm_provider = FixtureLLMProvider()
    elif os.getenv("ANTHROPIC_API_KEY", "").strip():
        llm_provider = AnthropicProvider()
    else:
        llm_provider = DisabledLLMProvider()
    llm_enabled = not isinstance(llm_provider, DisabledLLMProvider)
    # Keep the mapper installed even when AI is disabled: unknown tabular
    # formats must settle in needs_ai rather than being reported unsupported.
    column_mapper = AIColumnMappingService(provider=llm_provider, store=repository)
    categorization = (
        AICategorizationService(
            provider=llm_provider,
            repository=repository,
            auto_apply_threshold=settings.ai_category_auto_apply_threshold,
        )
        if llm_enabled
        else None
    )
    pipeline = IngestionPipeline(
        store=S3ObjectStore.from_env(),
        repository=repository,
        fx_provider=fx_provider,
        column_mapper=column_mapper,
        auto_enqueue_categorization=llm_enabled,
    )
    fx_refresh = FXRefreshService(repository=repository, provider=fx_provider)
    base_currency_rebuild = BaseCurrencyRebuildService(
        repository=repository,
        provider=fx_provider,
        max_staleness_days=settings.fx_max_staleness_days,
    )
    analytics_refresh = AnalyticsRefreshService(
        repository=PostgresAnalyticsRepository(settings.database_url)
    )
    runner = JobRunner(
        jobs=repository,
        pipeline=pipeline,
        timeout_seconds=settings.job_timeout_seconds,
        categorization=categorization,
        fx_refresh=fx_refresh,
        base_currency_rebuild=base_currency_rebuild,
        analytics_refresh=analytics_refresh,
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
