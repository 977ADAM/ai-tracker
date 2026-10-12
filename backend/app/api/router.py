"""Aggregates the resource routers; the `/api` prefix is added in main.py."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import (
    config,
    measurements,
    projects,
    provider_settings,
    providers,
    search_settings,
    seo_settings,
)

api_router = APIRouter()
api_router.include_router(config.router)
api_router.include_router(provider_settings.router)
api_router.include_router(providers.router)
api_router.include_router(search_settings.router)
api_router.include_router(seo_settings.router)
api_router.include_router(projects.router)
api_router.include_router(measurements.router)
