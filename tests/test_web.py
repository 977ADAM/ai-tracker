from fastapi.testclient import TestClient

from ai_tracker.gigachat import ProviderError
from ai_tracker.web import create_app
from ai_tracker.connections import ConnectionStore
from test_connections import MemorySecrets


class FakeProvider:
    def __init__(self):
        self.prompts = []

    def answer(self, prompt):
        self.prompts.append(prompt)
        if prompt == "ошибка":
            raise ProviderError("Сервис временно недоступен")
        return "Ромашка рекомендует этот вариант"


def test_python_app_exposes_api_only(tmp_path):
    client = TestClient(create_app(store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"]))
    assert client.get("/").status_code == 404
    assert client.get("/settings").status_code == 404
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/api/providers").status_code == 200


def test_returns_answers_and_summary(tmp_path):
    provider = FakeProvider()
    response = TestClient(create_app(provider, store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"])).post(
        "/api/check",
        json={"brand": " Ромашка ", "domain": " example.ru ", "prompts": ["успех", "другой"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["brand"] == "Ромашка"
    assert body["domain"] == "example.ru"
    assert body["summary"] == {"successful": 2, "failed": 0, "mentioned": 2}
    assert body["results"][0] == {
        "prompt": "успех",
        "answer": "Ромашка рекомендует этот вариант",
        "mentioned": True,
        "error": None,
    }
    assert provider.prompts == ["успех", "другой"]


def test_partial_failure_is_not_negative_mention(tmp_path):
    response = TestClient(create_app(FakeProvider(), store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"])).post(
        "/api/check", json={"brand": "Ромашка", "prompts": ["успех", "ошибка"]}
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"successful": 1, "failed": 1, "mentioned": 1}
    assert response.json()["results"][1] == {
        "prompt": "ошибка", "answer": None, "mentioned": None, "error": "Сервис временно недоступен"
    }


def test_invalid_request_does_not_call_provider(tmp_path):
    provider = FakeProvider()
    response = TestClient(create_app(provider, store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"])).post(
        "/api/check", json={"brand": "", "prompts": ["вопрос"]}
    )
    assert response.status_code == 400
    assert provider.prompts == []


def test_missing_credentials_is_service_error(monkeypatch, tmp_path):
    monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)
    response = TestClient(create_app(store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"])).post(
        "/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"]}
    )
    assert response.status_code == 200
    assert response.json()["checks"][0]["summary"]["failed"] == 1


def test_multiple_providers_are_isolated(tmp_path):
    secrets = MemorySecrets()
    store = ConnectionStore(tmp_path, secrets)
    store.save_connection({"api_key": "one"}, "gigachat")
    store.save_connection({"api_key": "two"}, "deepseek")
    calls = []

    class Stub:
        def __init__(self, id):
            self.id = id

        def answer(self, prompt):
            calls.append((self.id, prompt))
            if self.id == "deepseek":
                raise ProviderError("Сервис временно недоступен")
            return "Ромашка"

        def close(self):
            pass

    client = TestClient(create_app(store=store, provider_factory=lambda connection, key: Stub(connection["id"]), allowed_hosts=["testserver"]))
    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat", "deepseek"]})
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks[0]["summary"] == {"successful": 1, "failed": 0, "mentioned": 1}
    assert checks[1]["summary"] == {"successful": 0, "failed": 1, "mentioned": 0}
    assert calls == [("gigachat", "вопрос"), ("deepseek", "вопрос")]


def test_invalid_provider_selection_prevents_calls(tmp_path):
    store = ConnectionStore(tmp_path, MemorySecrets())
    calls = []
    client = TestClient(create_app(store=store, provider_factory=lambda c, k: calls.append(c), allowed_hosts=["testserver"]))
    for ids in (["missing"], ["gigachat", "gigachat"], ["gigachat"] * 6, []):
        assert client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ids}).status_code == 400
    assert calls == []


def test_settings_api_never_returns_key(tmp_path):
    client = TestClient(create_app(store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"]))
    created = client.post("/api/providers", json={"name": "Test", "kind": "openai", "endpoint": "https://api.example.com/v1/chat/completions", "model": "x", "api_key": "secret"})
    assert created.status_code == 200
    assert "secret" not in created.text
    assert "secret" not in client.get("/api/providers").text
    assert client.post("/api/providers", json={"name": "Bad", "kind": "openai", "endpoint": "http://localhost/chat/completions", "model": "x", "api_key": "secret"}).status_code == 400
    assert client.delete(f"/api/providers/{created.json()['id']}").status_code == 200


def test_provider_constructor_failure_is_isolated(tmp_path):
    store = ConnectionStore(tmp_path, MemorySecrets())
    store.save_connection({"api_key": "one"}, "gigachat")
    store.save_connection({"api_key": "two"}, "deepseek")
    class Stub:
        def answer(self, prompt): return "Ромашка"
        def close(self): pass
    def factory(connection, key):
        if connection["id"] == "gigachat":
            raise OSError("private path or key must not leak")
        return Stub()
    client = TestClient(create_app(store=store, provider_factory=factory, allowed_hosts=["testserver"]))
    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat", "deepseek"]})
    assert response.status_code == 200
    assert response.json()["checks"][0]["summary"]["failed"] == 1
    assert response.json()["checks"][1]["summary"]["successful"] == 1
    assert "private path" not in response.text
