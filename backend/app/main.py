"""Composition root: assemble the FastAPI application.

The application is built once at import, so `uvicorn app.main:app` needs no
factory call. Tests replace `get_container` through `dependency_overrides`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.deps import build_container
from app.api.errors import (
    app_error_handler,
    request_validation_handler,
    unhandled_error_handler,
)
from app.api.openapi import install_openapi
from app.api.router import api_router
from app.core import database
from app.core.config import Settings, load_env_file
from app.core.errors import AppError

TITLE = "ИИ-трекинг API"
VERSION = "0.1.0"
API_PREFIX = "/api"

# No-op when the host application (or pytest) already configured logging.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")

log = logging.getLogger("ai_tracker")

# Credentials come from the environment; the repository `.env` only fills the
# gaps, so an explicitly exported variable always wins.
load_env_file()


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings: Settings = application.state.settings
    container = application.state.container
    log.info("ИИ-трекинг API запущен: настройки подключений в %s", settings.config_dir)
    yield
    await container.measurements.close()
    await container.runs.close()
    await container.search.close()
    if container.search_client is not None:
        await container.search_client.aclose()
    # The background workers are stopped first, so no task can still hold a
    # connection while the pools of this process are closed.
    database.close_pools()
    log.info("ИИ-трекинг API остановлен")


settings = Settings.from_env()
container = build_container(settings)

app = FastAPI(
    title=TITLE,
    docs_url="/docs",
    version=VERSION,
    lifespan=lifespan
)

app.state.settings = settings
app.state.container = container

app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.include_router(api_router, prefix=API_PREFIX)
install_openapi(app, title=TITLE, version=VERSION)
