"""Aggregates the resource routers under the `/api` prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import checks, form, providers

API_PREFIX = "/api"


def build_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(form.router)
    router.include_router(providers.router)
    router.include_router(checks.router)
    return router


api_router = build_api_router()

__all__ = ["API_PREFIX", "api_router", "build_api_router"]
