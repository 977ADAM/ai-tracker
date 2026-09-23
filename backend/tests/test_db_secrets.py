"""The keyring-backed credential store delegates to the `keyring` package."""

from __future__ import annotations

import sys
import types

import pytest

from app.db.secrets import KeyringSecrets


class FakeKeyring(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("keyring")
        self.values: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []
        self.saved: list[tuple[str, str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.saved.append((service, username, password))
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.deleted.append((service, username))
        self.values.pop((service, username), None)


@pytest.fixture
def keyring_module(monkeypatch) -> FakeKeyring:
    module = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", module)
    return module


def test_reads_writes_and_deletes_through_keyring(keyring_module):
    secrets = KeyringSecrets()
    secrets.set_password("ai-tracker", "deepseek", "key")
    assert keyring_module.saved == [("ai-tracker", "deepseek", "key")]
    assert secrets.get_password("ai-tracker", "deepseek") == "key"
    secrets.delete_password("ai-tracker", "deepseek")
    assert keyring_module.deleted == [("ai-tracker", "deepseek")]
    assert secrets.get_password("ai-tracker", "deepseek") is None


def test_an_unavailable_keyring_error_reaches_the_caller(keyring_module, monkeypatch):
    secrets = KeyringSecrets()

    def explode(*_args, **_kwargs):
        raise RuntimeError("no backend")

    monkeypatch.setattr(keyring_module, "get_password", explode)
    with pytest.raises(RuntimeError):
        secrets.get_password("ai-tracker", "deepseek")
