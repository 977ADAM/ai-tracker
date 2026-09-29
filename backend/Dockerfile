FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --extra docker

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AI_TRACKER_CONFIG_DIR=/data \
    HOME=/data \
    PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring \
    PORT=8000

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app

RUN useradd --uid 10001 --user-group --home-dir /data --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /data /app

USER app
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
