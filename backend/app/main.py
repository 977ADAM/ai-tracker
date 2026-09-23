"""Composition root: build the FastAPI application and wire its dependencies."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.deps import build_container
from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.db.secrets import SecretStore
from app.domain.providers import ProviderFactory

TITLE = "ИИ-трекинг API"


def create_app(
    settings: Settings | None = None,
    *,
    repository: ConnectionRepository | None = None,
    secrets: SecretStore | None = None,
    provider_factory: ProviderFactory | None = None,
) -> FastAPI:
    """Build one app instance. Tests pass a settings object and fake collaborators."""
    resolved = settings or Settings.from_env()
    application = FastAPI(title=TITLE)
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(resolved.allowed_hosts),
    )
    application.state.container = build_container(
        resolved,
        repository=repository,
        secrets=secrets,
        provider_factory=provider_factory,
    )
    register_error_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
