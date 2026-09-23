"""Wiring of services for one app instance, plus FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.db.connections import ConnectionRepository
from app.db.secrets import KeyringSecrets, SecretStore
from app.domain.providers import ProviderFactory
from app.integrations.factory import build_provider
from app.service.checks import CheckService
from app.service.connections import ConnectionService
from app.service.form import FormService


@dataclass(frozen=True)
class Container:
    """Everything the routers need, built once per app instance."""

    settings: Settings
    repository: ConnectionRepository
    connections: ConnectionService
    checks: CheckService
    form: FormService


def build_container(
    settings: Settings,
    *,
    repository: ConnectionRepository | None = None,
    secrets: SecretStore | None = None,
    provider_factory: ProviderFactory | None = None,
) -> Container:
    if repository is None:
        repository = ConnectionRepository(
            Path(settings.config_dir),
            secrets or KeyringSecrets(),
            presets=settings.presets,
            env_api_key=settings.env_api_key,
            service_name=settings.service_name,
        )
    connections = ConnectionService(repository, settings)
    factory = provider_factory or (lambda connection, key: build_provider(connection, key, settings))
    return Container(
        settings=settings,
        repository=repository,
        connections=connections,
        checks=CheckService(connections, factory),
        form=FormService(connections),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_connection_service(container: ContainerDep) -> ConnectionService:
    return container.connections


def get_check_service(container: ContainerDep) -> CheckService:
    return container.checks


def get_form_service(container: ContainerDep) -> FormService:
    return container.form


ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]
CheckServiceDep = Annotated[CheckService, Depends(get_check_service)]
FormServiceDep = Annotated[FormService, Depends(get_form_service)]
