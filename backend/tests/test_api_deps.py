"""The public surface of the `app.api.deps` package.

Routers and tests import the wiring from the package, so the re-exports are the
contract: every name in `__all__` must resolve, and every `…Dep` alias must be
built on the accessor it names — an alias that quietly pointed at another service
would hand a router the wrong object.
"""

from __future__ import annotations

from typing import Annotated, get_args

from fastapi.params import Depends

from app.api import deps
from app.api.deps import dependencies

DEPENDENCIES = {
    "ConnectionServiceDep": "get_connection_service",
    "CheckServiceDep": "get_check_service",
    "FormServiceDep": "get_form_service",
    "ProviderSettingsServiceDep": "get_provider_settings_service",
    "ConfigServiceDep": "get_config_service",
    "SearchServiceDep": "get_search_service",
    "SearchSettingsServiceDep": "get_search_settings_service",
    "RunServiceDep": "get_run_service",
    "SeoSettingsServiceDep": "get_seo_settings_service",
}


def test_every_public_name_of_the_package_resolves():
    assert set(deps.__all__) == set(DEPENDENCIES) | {
        "Container", "ContainerDep", "build_container", "get_container",
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
        "SeoSettingsServiceDep": "seo_settings",
    }

    assert set(fields.values()) <= set(container)
