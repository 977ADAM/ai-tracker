"""Aggregates the resource routers; the `/api` prefix is added in main.py."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import (
    checks,
    config,
    form,
    measurements,
    projects,
    provider_settings,
    providers,
    runs,
    search,
    search_settings,
    seo,
    seo_chats,
    seo_settings,
)

api_router = APIRouter()
api_router.include_router(config.router)
api_router.include_router(form.router)
api_router.include_router(provider_settings.router)
api_router.include_router(providers.router)
api_router.include_router(checks.router)
api_router.include_router(search_settings.router)
api_router.include_router(search.router)
api_router.include_router(runs.router)
# The settings resource is registered before the analyses resource.
api_router.include_router(seo_settings.router)
api_router.include_router(seo.router)
# The chat resource can start an analysis, so it is registered after it.
api_router.include_router(seo_chats.router)


api_router.include_router(projects.router)
api_router.include_router(measurements.router)
