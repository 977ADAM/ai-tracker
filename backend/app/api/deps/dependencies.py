"""The HTTP edge: request-scoped access to the container of one application.

Every router asks for a service through one of the `…Dep` aliases, so a handler
declares what it needs and nothing about how it was built. The container itself
is created once per app instance and stored on the application, which is what
makes it replaceable in tests through `dependency_overrides`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.deps.container import Container
from app.service.chat import ChatService
from app.service.checks import CheckService
from app.service.config import ConfigService
from app.service.connections import ConnectionService
from app.service.form import FormService
from app.service.provider_settings import ProviderSettingsService
from app.service.runs import RunService
from app.service.search import SearchService
from app.service.search_settings import SearchSettingsService
from app.service.seo import SeoService
from app.service.seo_settings import SeoSettingsService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_connection_service(container: ContainerDep) -> ConnectionService:
    return container.connections


def get_check_service(container: ContainerDep) -> CheckService:
    return container.checks


def get_form_service(container: ContainerDep) -> FormService:
    return container.form


def get_provider_settings_service(container: ContainerDep) -> ProviderSettingsService:
    return container.provider_settings


def get_config_service(container: ContainerDep) -> ConfigService:
    return container.config


def get_search_service(container: ContainerDep) -> SearchService:
    return container.search


def get_search_settings_service(container: ContainerDep) -> SearchSettingsService:
    return container.search_settings


def get_run_service(container: ContainerDep) -> RunService:
    return container.runs


def get_seo_service(container: ContainerDep) -> SeoService:
    return container.seo_service


def get_seo_settings_service(container: ContainerDep) -> SeoSettingsService:
    return container.seo_settings


def get_chat_service(container: ContainerDep) -> ChatService:
    return container.chat_service


ContainerDep = Annotated[Container, Depends(get_container)]
ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]
CheckServiceDep = Annotated[CheckService, Depends(get_check_service)]
FormServiceDep = Annotated[FormService, Depends(get_form_service)]
ProviderSettingsServiceDep = Annotated[ProviderSettingsService, Depends(get_provider_settings_service)]
ConfigServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
SearchSettingsServiceDep = Annotated[SearchSettingsService, Depends(get_search_settings_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SeoServiceDep = Annotated[SeoService, Depends(get_seo_service)]
SeoSettingsServiceDep = Annotated[SeoSettingsService, Depends(get_seo_settings_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
