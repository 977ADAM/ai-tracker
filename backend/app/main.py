from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .connections import ConnectionStore, KeyringSecrets
from app.api.router import router

log = logging.getLogger("ai_tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="ИИ-трекинг API", lifespan=lifespan)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1"],
)

app.state.provider = None

app.include_router(router)