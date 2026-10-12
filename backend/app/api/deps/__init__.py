"""Composition of the application: the container and the FastAPI dependencies.

The wiring is kept in layers instead of one module, and every one of them is
re-exported here, so a caller keeps importing from `app.api.deps`:

* `container` — the composition root: one `Container` per app instance.
* `dependencies` — the request-scoped accessors the routers depend on.
"""

from __future__ import annotations

from app.api.deps.container import Container, build_container
from app.api.deps.dependencies import (
    ConfigServiceDep,
    ConnectionServiceDep,
    ContainerDep,
    ProviderSettingsServiceDep,
    SearchSettingsServiceDep,
    SeoSettingsServiceDep,
    get_config_service,
    get_connection_service,
    get_container,
    get_provider_settings_service,
    get_search_settings_service,
    get_seo_settings_service,
)

__all__ = [
    "ConfigServiceDep",
    "ConnectionServiceDep",
    "Container",
    "ContainerDep",
    "ProviderSettingsServiceDep",
    "SearchSettingsServiceDep",
    "SeoSettingsServiceDep",
    "build_container",
    "get_config_service",
    "get_connection_service",
    "get_container",
    "get_provider_settings_service",
    "get_search_settings_service",
    "get_seo_settings_service",
]
