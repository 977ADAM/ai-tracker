"""Aggregates the resource routers; the `/api` prefix is added in main.py."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import checks, form, provider_settings, providers

api_router = APIRouter()
api_router.include_router(form.router)
api_router.include_router(provider_settings.router)
api_router.include_router(providers.router)
api_router.include_router(checks.router)
