"""Resolution of effective Yandex settings and safe public fields."""

from dataclasses import FrozenInstanceError

import pytest

from app.domain.search_settings import SearchSettings


def test_missing_values_default_to_enabled_without_credentials():
    settings = SearchSettings.resolve()
    assert settings.enabled is True
    assert settings.api_key is None
    assert settings.folder_id is None
    assert settings.api_key_source == "none"
    assert settings.folder_id_source == "none"
    assert settings.has_api_key is False


def test_missing_enabled_field_defaults_to_true():
    assert SearchSettings.resolve(enabled=None, env_api_key="env-key").enabled is True


def test_ui_credentials_override_environment_independently():
    settings = SearchSettings.resolve(
        enabled=False, ui_api_key="ui-key", ui_folder_id="ui-folder",
        env_api_key="env-key", env_folder_id="env-folder",
    )
    assert settings.enabled is False
    assert settings.api_key == "ui-key"
    assert settings.folder_id == "ui-folder"
    assert settings.api_key_source == "ui"
    assert settings.folder_id_source == "ui"
    assert settings.has_api_key is True


def test_mixed_sources_are_independent():
    settings = SearchSettings.resolve(
        ui_api_key="ui-key", env_api_key="env-key", env_folder_id="env-folder",
    )
    assert (settings.api_key, settings.api_key_source) == ("ui-key", "ui")
    assert (settings.folder_id, settings.folder_id_source) == ("env-folder", "env")


def test_blank_values_are_absent_and_value_is_immutable():
    settings = SearchSettings.resolve(ui_api_key="  ", env_folder_id=" ")
    assert (settings.api_key, settings.api_key_source) == (None, "none")
    assert (settings.folder_id, settings.folder_id_source) == (None, "none")
    with pytest.raises(FrozenInstanceError):
        settings.enabled = False
