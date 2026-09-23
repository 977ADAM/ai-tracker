from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .connections import ConnectionStore, KeyringSecrets
from .web import default_provider

log = logging.getLogger("ai_tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def _config_dir() -> Path:
    return Path(os.getenv("AI_TRACKER_CONFIG_DIR", Path.home() / ".config" / "ai-tracker"))


app = FastAPI(title="ИИ-трекинг API", lifespan=lifespan)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1"],
)

app.state.store = ConnectionStore(_config_dir(), KeyringSecrets())
app.state.provider = None
app.state.provider_factory = default_provider

app.include_router(router)