"""The public surface of the `app.api.deps` package.

Routers and tests import the wiring from the package, so the re-exports are the
contract: every name in `__all__` must resolve, and every `…Dep` alias must be
built on the accessor it names — an alias that quietly pointed at another service
would hand a router the wrong object.
"""

from __future__ import annotations

from typing import Annotated, get_args

import pytest
from fastapi.params import Depends

from app.api import deps
from app.api.deps import dependencies
from app.core.errors import ConfigurationError
from app.domain.seo_llm import LLM_NOT_CONFIGURED

DEPENDENCIES = {
    "ConnectionServiceDep": "get_connection_service",
    "CheckServiceDep": "get_check_service",
    "FormServiceDep": "get_form_service",
    "ProviderSettingsServiceDep": "get_provider_settings_service",
    "ConfigServiceDep": "get_config_service",
    "SearchServiceDep": "get_search_service",
    "SearchSettingsServiceDep": "get_search_settings_service",
    "RunServiceDep": "get_run_service",
    "SeoServiceDep": "get_seo_service",
    "SeoSettingsServiceDep": "get_seo_settings_service",
    "ChatServiceDep": "get_chat_service",
}


def test_every_public_name_of_the_package_resolves():
    assert set(deps.__all__) == set(DEPENDENCIES) | {
        "Container", "ContainerDep", "UnconfiguredAgentModel", "agent_checkpointer", "build_container",
        "checkpoint_probe", "get_container", "make_seo_toolbox_factory",
        *DEPENDENCIES.values(),
    }
    for name in deps.__all__:
        assert getattr(deps, name) is not None


def test_the_package_surface_is_the_same_object_as_its_layer():
    """FastAPI overrides dependencies by identity, so the re-export must be it."""
    assert deps.get_container is dependencies.get_container
    assert deps.Container is dependencies.Container


def test_every_dependency_alias_is_built_on_the_accessor_it_names():
    for alias, accessor in DEPENDENCIES.items():
        annotation: Annotated = getattr(deps, alias)
        dependency = get_args(annotation)[1]

        assert isinstance(dependency, Depends)
        assert dependency.dependency is getattr(deps, accessor)


def test_the_routers_get_the_service_their_alias_names():
    """The aliases and the container fields agree on every service."""
    container = deps.Container.__dataclass_fields__
    fields = {
        "ConnectionServiceDep": "connections",
        "CheckServiceDep": "checks",
        "FormServiceDep": "form",
        "ProviderSettingsServiceDep": "provider_settings",
        "ConfigServiceDep": "config",
        "SearchServiceDep": "search",
        "SearchSettingsServiceDep": "search_settings",
        "RunServiceDep": "runs",
        "SeoServiceDep": "seo_service",
        "SeoSettingsServiceDep": "seo_settings",
        "ChatServiceDep": "chat_service",
    }

    assert set(fields.values()) <= set(container)


def test_the_unconfigured_stand_in_names_the_missing_llm_on_every_call():
    """A stand-in reached by mistake must still report the real reason.

    `BaseChatModel.bind_tools` answers a bare `NotImplementedError`, so without
    its own binding the stand-in would hide an unconfigured service LLM behind a
    crash that says nothing about the configuration.
    """
    stand_in = deps.UnconfiguredAgentModel()

    with pytest.raises(ConfigurationError) as raised:
        stand_in.bind_tools([])

    assert str(raised.value) == LLM_NOT_CONFIGURED
