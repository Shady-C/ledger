FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12-slim AS runtime

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ghostscript libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY services/worker/pyproject.toml services/worker/uv.lock services/worker/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/worker/worker ./worker
RUN uv sync --frozen --no-dev --no-editable

RUN addgroup --system ledger && adduser --system --ingroup ledger ledger
USER ledger

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import worker; print('ok')"]

CMD ["ledger-worker"]
