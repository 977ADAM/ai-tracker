"""Composition of the application: the container and the FastAPI dependencies.

The wiring is kept in layers instead of one module, and every one of them is
re-exported here, so a caller keeps importing from `app.api.deps`:

* `container` — the composition root: one `Container` per app instance.
* `fallbacks` — the stand-in model that keeps the app bootable while the SEO
  service LLM is not configured yet.
* `checkpoints` — the graph checkpoint file of the SEO agent runtime.
* `dependencies` — the request-scoped accessors the routers depend on.
"""

from __future__ import annotations

from app.api.deps.checkpoints import agent_checkpointer, checkpoint_probe
from app.api.deps.container import Container, build_container, make_seo_toolbox_factory
from app.api.deps.dependencies import (
    CheckServiceDep,
    ConfigServiceDep,
    ConnectionServiceDep,
    ContainerDep,
    FormServiceDep,
    ProviderSettingsServiceDep,
    RunServiceDep,
    SearchServiceDep,
    SearchSettingsServiceDep,
    SeoServiceDep,
    SeoSettingsServiceDep,
    get_check_service,
    get_config_service,
    get_connection_service,
    get_container,
    get_form_service,
    get_provider_settings_service,
    get_run_service,
    get_search_service,
    get_search_settings_service,
    get_seo_service,
    get_seo_settings_service,
)
from app.api.deps.fallbacks import UnconfiguredAgentModel

__all__ = [
    "CheckServiceDep",
    "ConfigServiceDep",
    "ConnectionServiceDep",
    "Container",
    "ContainerDep",
    "FormServiceDep",
    "ProviderSettingsServiceDep",
    "RunServiceDep",
    "SearchServiceDep",
    "SearchSettingsServiceDep",
    "SeoServiceDep",
    "SeoSettingsServiceDep",
    "UnconfiguredAgentModel",
    "agent_checkpointer",
    "build_container",
    "checkpoint_probe",
    "get_check_service",
    "get_config_service",
    "get_connection_service",
    "get_container",
    "get_form_service",
    "get_provider_settings_service",
    "get_run_service",
    "get_search_service",
    "get_search_settings_service",
    "get_seo_service",
    "get_seo_settings_service",
    "make_seo_toolbox_factory",
]
