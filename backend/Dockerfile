# The FastAPI backend. Dependencies come from `uv.lock`, so the image is
# reproducible; the application code is copied last, so a source change only
# rebuilds the last layer.
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

# The virtual environment lives outside the project, so the runtime stage can
# copy it as one directory.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
# `docker` is the optional extra with the file-backed keyring: a container has
# no OS keyring, and without a backend the settings screen cannot save a key.
RUN uv sync --frozen --no-dev --extra docker


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Everything the app writes — providers.json, runs.sqlite3, the agent
    # checkpoints, and the key file — lives in the mounted volume.
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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/providers', timeout=4).status < 500 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
