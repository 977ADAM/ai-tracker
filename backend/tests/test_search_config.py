"""Yandex search credentials and the wiring of the search service."""

from __future__ import annotations

import asyncio

from app.api.deps import build_container
from app.core.config import Settings, load_env_file
from app.integrations.yandex_search import YandexSearchGateway


def test_prefixed_variables_win_over_the_legacy_names():
    settings = Settings.from_env(
        {
            "YANDEX_SEARCH_API_KEY": "new-key",
            "API_KEY": "old-key",
            "YANDEX_SEARCH_FOLDER_ID": "new-folder",
            "FOLDER_ID": "old-folder",
        }
    )

    assert settings.yandex_search_api_key == "new-key"
    assert settings.yandex_search_folder_id == "new-folder"


def test_legacy_variables_are_the_fallback():
    settings = Settings.from_env({"API_KEY": "old-key", "FOLDER_ID": "old-folder"})

    assert settings.yandex_search_api_key == "old-key"
    assert settings.yandex_search_folder_id == "old-folder"


def test_empty_values_are_ignored():
    settings = Settings.from_env(
        {
            "YANDEX_SEARCH_API_KEY": "",
            "API_KEY": "old-key",
            "YANDEX_SEARCH_FOLDER_ID": "   ",
            "FOLDER_ID": "old-folder",
        }
    )

    assert settings.yandex_search_api_key == "old-key"
    assert settings.yandex_search_folder_id == "old-folder"


def test_absent_credentials_stay_none():
    settings = Settings.from_env({})

    assert settings.yandex_search_api_key is None
    assert settings.yandex_search_folder_id is None


def test_a_container_without_credentials_has_no_gateway():
    container = build_container(Settings())

    assert container.search.gateway is None
    assert container.search_client is None


def test_a_container_builds_the_gateway_from_credentials():
    container = build_container(Settings(yandex_search_api_key="key", yandex_search_folder_id="folder"))

    try:
        assert isinstance(container.search.gateway, YandexSearchGateway)
        assert container.search.gateway.folder_id == "folder"
        assert container.search_client is not None
        assert container.search.gateway.client is container.search_client
    finally:
        if container.search_client is not None:
            asyncio.run(container.search_client.aclose())


def test_an_injected_gateway_wins_over_the_environment():
    injected = object()
    container = build_container(
        Settings(yandex_search_api_key="key", yandex_search_folder_id="folder"),
        search_gateway=injected,
    )

    assert container.search.gateway is injected
    assert container.search_client is None


def test_the_root_env_file_never_overrides_the_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("YANDEX_SEARCH_API_KEY=from-file\nYANDEX_SEARCH_FOLDER_ID=from-file\n", encoding="utf-8")
    monkeypatch.setenv("YANDEX_SEARCH_API_KEY", "from-environment")
    monkeypatch.delenv("YANDEX_SEARCH_FOLDER_ID", raising=False)

    load_env_file(env_file)

    assert Settings.from_env().yandex_search_api_key == "from-environment"
    assert Settings.from_env().yandex_search_folder_id == "from-file"


def test_a_missing_env_file_is_not_an_error(tmp_path):
    load_env_file(tmp_path / "missing.env")
