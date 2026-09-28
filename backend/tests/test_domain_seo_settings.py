"""Endpoint rules and resolved values for the SEO service LLM."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from app.domain.seo_settings import SeoSettings, validate_seo_endpoint

from app.core.errors import ValidationError

CHAT_PATH = "/v1/chat/completions"


@pytest.mark.parametrize(
    "url",
    [
        f"https://api.example.com{CHAT_PATH}",
        f"https://api.example.com:8443{CHAT_PATH}",
        f"https://localhost{CHAT_PATH}",
        f"https://127.0.0.1{CHAT_PATH}",
        f"http://localhost:8080/api{CHAT_PATH}",
        f"http://127.0.0.1{CHAT_PATH}",
        f"http://127.5.5.5:11434{CHAT_PATH}",
        f"http://[::1]:8080{CHAT_PATH}",
    ],
)
def test_accepts_safe_seo_endpoint(url):
    assert validate_seo_endpoint(url) == url


@pytest.mark.parametrize(
    "url",
    [
        f"http://api.example.com{CHAT_PATH}",
        "http://192.168.1.10" + CHAT_PATH,
        f"https://192.168.1.10{CHAT_PATH}",
        "https://10.0.0.1" + CHAT_PATH,
        "https://example.com/v1/other",
        f"https://example.com{CHAT_PATH}/",
        f"https://u:p@api.example.com{CHAT_PATH}",
        f"https://api.example.com{CHAT_PATH}?x=1",
        f"https://api.example.com{CHAT_PATH}#x",
        "https://api.example.com/v1//chat/completions",
        "https://api.example.com/v1\\chat\\completions",
        "https://api.example.com/v1/chat completions",
        "file:///v1/chat/completions",
        "api.example.com/v1/chat/completions",
        "https:///v1/chat/completions",
        "https://api.example.com:notaport/v1/chat/completions",
    ],
)
def test_rejects_unsafe_seo_endpoint(url):
    with pytest.raises(ValidationError):
        validate_seo_endpoint(url)


@pytest.mark.parametrize("value", [None, 42, b"https://api.example.com/v1/chat/completions"])
def test_rejects_non_string_endpoint(value):
    with pytest.raises(ValidationError):
        validate_seo_endpoint(value)


def test_rejects_oversized_endpoint():
    with pytest.raises(ValidationError):
        validate_seo_endpoint("https://api.example.com" + CHAT_PATH + "x" * 2048)


def test_ui_values_win_over_the_environment_per_field():
    settings = SeoSettings.resolve(
        ui_model="ui-model",
        env_endpoint=f"https://env.example.com{CHAT_PATH}",
        env_model="env-model",
        env_api_key="env-key",
    )

    assert (settings.endpoint, settings.endpoint_source) == (f"https://env.example.com{CHAT_PATH}", "env")
    assert (settings.model, settings.model_source) == ("ui-model", "ui")
    assert (settings.api_key, settings.api_key_source) == ("env-key", "env")
    assert settings.has_api_key is True
    assert settings.configured is True


def test_ui_values_are_trimmed_and_blank_environment_values_are_ignored():
    settings = SeoSettings.resolve(
        ui_endpoint=f"  https://api.example.com{CHAT_PATH}  ",
        ui_model="  ui-model  ",
        ui_api_key="  ui-key  ",
        env_api_key="   ",
    )

    assert (settings.endpoint, settings.model) == (f"https://api.example.com{CHAT_PATH}", "ui-model")
    assert settings.api_key == "ui-key"
    assert (settings.endpoint_source, settings.model_source, settings.api_key_source) == ("ui", "ui", "ui")


def test_without_any_values_the_settings_are_empty_and_unconfigured():
    settings = SeoSettings.resolve()

    assert (settings.endpoint, settings.model, settings.api_key) == ("", "", None)
    assert (settings.endpoint_source, settings.model_source, settings.api_key_source) == ("none", "none", "none")
    assert settings.has_api_key is False
    assert settings.configured is False


def test_the_resolved_settings_are_immutable():
    settings = SeoSettings.resolve(ui_endpoint=f"https://api.example.com{CHAT_PATH}", ui_model="m", ui_api_key="k")

    with pytest.raises(FrozenInstanceError):
        settings.model = "other"  # type: ignore[misc]


def test_the_resolved_value_keeps_the_key_out_of_repr():
    settings = SeoSettings.resolve(ui_endpoint=f"https://api.example.com{CHAT_PATH}", ui_model="m", ui_api_key="private-key")

    assert "private-key" not in repr(settings)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ui_endpoint": f"http://api.example.com{CHAT_PATH}"},
        {"ui_endpoint": f"https://192.168.0.1{CHAT_PATH}"},
        {"env_endpoint": f"http://api.example.com{CHAT_PATH}"},
        {"env_endpoint": "https://example.com/v1/other"},
    ],
)
def test_resolution_rejects_an_unsafe_endpoint(kwargs):
    with pytest.raises(ValidationError):
        SeoSettings.resolve(**kwargs)
