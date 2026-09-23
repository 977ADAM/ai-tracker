import pytest

from ai_tracker.connections import ConnectionStore, ConnectionError, validate_endpoint


class MemorySecrets:
    def __init__(self):
        self.values = {}
        self.fail = False

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        if self.fail:
            raise RuntimeError("unavailable")
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_presets_and_custom_roundtrip(tmp_path):
    secrets = MemorySecrets()
    store = ConnectionStore(tmp_path, secrets)
    assert [item["id"] for item in store.list_connections()] == ["gigachat", "deepseek"]
    saved = store.save_connection({"name": "Тест", "kind": "openai", "endpoint": "https://api.example.com/v1/chat/completions", "model": "example-model", "api_key": "secret-value"})
    assert store.get_key(saved["id"]) == "secret-value"
    assert "secret-value" not in (tmp_path / "providers.json").read_text()
    assert "api_key" not in saved
    assert (tmp_path / "providers.json").stat().st_mode & 0o777 == 0o600
    assert ConnectionStore(tmp_path, secrets).list_connections()[2]["name"] == "Тест"
    store.save_connection({"name": "Новый", "api_key": ""}, saved["id"])
    assert store.get_key(saved["id"]) == "secret-value"
    store.delete_connection(saved["id"])
    assert store.get_key(saved["id"]) is None
    assert len(store.list_connections()) == 2


def test_failed_secret_write_preserves_connection(tmp_path):
    secrets = MemorySecrets()
    store = ConnectionStore(tmp_path, secrets)
    saved = store.save_connection({"name": "Тест", "kind": "openai", "endpoint": "https://api.example.com/v1/chat/completions", "model": "old", "api_key": "old-key"})
    before = (tmp_path / "providers.json").read_text()
    secrets.fail = True
    with pytest.raises(ConnectionError):
        store.save_connection({"name": "Изменен", "model": "new", "api_key": "new-key"}, saved["id"])
    assert (tmp_path / "providers.json").read_text() == before
    assert store.get_key(saved["id"]) == "old-key"


def test_unavailable_keyring_refuses_key_save(tmp_path):
    secrets = MemorySecrets()
    secrets.fail = True
    with pytest.raises(ConnectionError):
        ConnectionStore(tmp_path, secrets).save_connection({"api_key": "x"}, "gigachat")


@pytest.mark.parametrize("url", [
    "http://api.example.com/v1/chat/completions", "https://127.0.0.1/v1/chat/completions",
    "https://localhost/v1/chat/completions", "https://foo.local/v1/chat/completions",
    "https://intranet/v1/chat/completions", "https://u:p@api.example.com/v1/chat/completions",
    "https://api.example.com/v1/chat/completions?x=1", "https://api.example.com/v1/chat/completions#x",
    "https://api.example.com/v1/other", "https://api.example.com:8443/v1/chat/completions",
])
def test_rejects_unsafe_endpoint(url):
    with pytest.raises(ConnectionError):
        validate_endpoint(url)


@pytest.mark.parametrize("url", ["https://api.example.com/v1/chat/completions", "https://api.example.com/api/v1/chat/completions"])
def test_accepts_chat_endpoint(url):
    assert validate_endpoint(url) == url


def test_builtin_key_only_edit(tmp_path):
    store = ConnectionStore(tmp_path, MemorySecrets())
    saved = store.save_connection({"api_key": "abc", "scope": "GIGACHAT_API_CORP"}, "gigachat")
    assert saved["model"] == "GigaChat"
    assert store.get_key("gigachat") == "abc"
    assert saved["scope"] == "GIGACHAT_API_CORP"


def test_reset_builtin_with_environment_key_and_no_saved_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    class StrictSecrets(MemorySecrets):
        def delete_password(self, service, username):
            if (service, username) not in self.values:
                raise RuntimeError("missing key")
            super().delete_password(service, username)
    secrets = StrictSecrets()
    store = ConnectionStore(tmp_path, secrets)
    store.delete_connection("deepseek")
    assert store.get_key("deepseek") == "env-key"
    assert secrets.values == {}
