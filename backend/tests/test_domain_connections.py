"""Connection payload rules and the public connection view."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.connections import (
    api_key_from_payload,
    can_delete,
    can_reset,
    connection_from_preset,
    editable_fields,
    new_custom_connection,
    public_view,
    updated_custom_connection,
    updated_preset,
)
from app.domain.models import Connection
from tests.fakes import DEEPSEEK_PRESET, ENDPOINT, GIGACHAT_PRESET

SECRET_MARKER = "secret-value"

CUSTOM = {
    "name": "Тест",
    "kind": "openai",
    "endpoint": ENDPOINT,
    "model": "example-model",
    "api_key": SECRET_MARKER,
}


def custom_connection() -> Connection:
    return new_custom_connection({key: value for key, value in CUSTOM.items() if key != "api_key"})


def test_custom_connection_gets_a_generated_id():
    connection = custom_connection()
    assert connection.kind == "openai"
    assert connection.name == "Тест"
    assert connection.endpoint == ENDPOINT
    assert connection.model == "example-model"
    assert connection.id and not connection.preset


def test_public_view_never_contains_a_key():
    view = public_view(custom_connection(), configured=True)
    assert SECRET_MARKER not in str(view)
    assert "api_key" not in view
    assert view["configured"] is True
    assert view["status_label"] == "Готово к проверке"
    assert view["editable_fields"] == ["name", "endpoint", "model", "api_key"]
    assert view["can_reset"] is False
    assert view["can_delete"] is True
    assert view["delete_label"] == "Удалить"
    assert view["delete_prompt"] == "Удалить подключение «Тест» и его ключ?"


def test_unconfigured_view_asks_for_a_key():
    view = public_view(custom_connection(), configured=False)
    assert view["status_label"] == "Нужен API-ключ"


def test_gigachat_preset_can_change_its_scope_and_key():
    connection = connection_from_preset(GIGACHAT_PRESET)
    assert editable_fields(connection) == ["scope", "api_key"]
    assert can_reset(connection) is True
    assert can_delete(connection) is False
    view = public_view(connection, configured=False)
    assert view["scope"] == "GIGACHAT_API_PERS"
    assert view["delete_label"] == "Сбросить ключ"
    assert "Ключ из переменной среды" in view["delete_prompt"]
    assert view["delete_success"] == "Сохранённый ключ сброшен"


def test_openai_preset_only_edits_its_key_and_hides_scope():
    connection = connection_from_preset(DEEPSEEK_PRESET)
    assert editable_fields(connection) == ["api_key"]
    assert "scope" not in public_view(connection, configured=False)


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "endpoint": ENDPOINT, "model": "m"},
        {"name": "x" * 101, "endpoint": ENDPOINT, "model": "m"},
        {"name": "n", "endpoint": ENDPOINT, "model": ""},
        {"name": "n", "endpoint": ENDPOINT, "model": "m" * 101},
        {"name": "n", "endpoint": "http://api.example.com/v1/chat/completions", "model": "m"},
        {"name": "n", "endpoint": ENDPOINT, "model": "m", "kind": "anthropic"},
    ],
)
def test_new_connection_rejects_invalid_payloads(payload):
    with pytest.raises(ValidationError):
        new_custom_connection(payload)


def test_update_merges_the_previous_connection():
    previous = custom_connection()
    updated = updated_custom_connection(previous, {"model": "new-model"})
    assert updated.id == previous.id
    assert updated.model == "new-model"
    assert updated.name == previous.name
    assert updated.endpoint == previous.endpoint


def test_preset_update_rejects_fields_it_does_not_own():
    connection = connection_from_preset(GIGACHAT_PRESET)
    with pytest.raises(ValidationError):
        updated_preset(connection, {"name": "Другое"}, "GIGACHAT_API_PERS")


def test_preset_update_keeps_model_and_changes_scope():
    connection = connection_from_preset(GIGACHAT_PRESET)
    updated = updated_preset(connection, {"scope": "GIGACHAT_API_CORP"}, "GIGACHAT_API_PERS")
    assert updated.model == "GigaChat"
    assert updated.scope == "GIGACHAT_API_CORP"
    assert updated.preset is True


def test_preset_update_rejects_an_unknown_scope():
    connection = connection_from_preset(GIGACHAT_PRESET)
    with pytest.raises(ValidationError):
        updated_preset(connection, {"scope": "OTHER"}, "GIGACHAT_API_PERS")


def test_preset_update_falls_back_to_the_default_scope():
    connection = Connection(id="gigachat", name="GigaChat", kind="gigachat", model="GigaChat", preset=True)
    updated = updated_preset(connection, {"api_key": "k"}, "GIGACHAT_API_B2B")
    assert updated.scope == "GIGACHAT_API_B2B"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({}, None), ({"api_key": None}, None), ({"api_key": ""}, None), ({"api_key": "   "}, None), ({"api_key": " k "}, "k")],
)
def test_api_key_validation_accepts_blank_as_keep(payload, expected):
    assert api_key_from_payload(payload) == expected


@pytest.mark.parametrize("value", [42, ["k"], "x" * 10_001])
def test_api_key_validation_rejects_bad_values(value):
    with pytest.raises(ValidationError):
        api_key_from_payload({"api_key": value})
