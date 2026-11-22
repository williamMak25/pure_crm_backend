# syntax=docker/dockerfile:1
# Two targets:
#   dev   dependencies incl. pytest/ruff, code is bind-mounted, runs with --reload
#   prod  (default) runtime dependencies only, code baked into the image
FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /app
RUN useradd --system --uid 1001 --home /app appuser

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"
EXPOSE 8000


FROM base AS dev

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen && chown -R appuser /app
USER appuser

CMD ["app", "run", "--reload", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS prod

# dependencies first so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev && chown -R appuser /app
USER appuser

CMD ["app", "run", "--host", "0.0.0.0", "--port", "8000"]
