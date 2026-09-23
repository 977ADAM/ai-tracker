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
    assert body["summary"] == {"successful": 2, "failed": 0, "mentioned": 2, "mention_percent": 100,
                               "visibility_label": "100%", "mentions_label": "2 из 2 успешных ответов", "errors_label": "0 ошибок API"}
    assert body["results"][0] == {
        "prompt": "успех",
        "answer": "Ромашка рекомендует этот вариант",
        "mentioned": True,
        "error": None,
        "status": "mentioned",
    }
    assert provider.prompts == ["успех", "другой"]


def test_partial_failure_is_not_negative_mention(tmp_path):
    response = TestClient(create_app(FakeProvider(), store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"])).post(
        "/api/check", json={"brand": "Ромашка", "prompts": ["успех", "ошибка"]}
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"successful": 1, "failed": 1, "mentioned": 1, "mention_percent": 100,
                                           "visibility_label": "100%", "mentions_label": "1 из 1 успешных ответов", "errors_label": "1 ошибка API"}
    assert response.json()["results"][1] == {
        "prompt": "ошибка", "answer": None, "mentioned": None, "error": "Сервис временно недоступен", "status": "error"
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


def test_api_owns_form_rules_and_provider_actions(tmp_path):
    client = TestClient(create_app(store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"]))
    form = client.get("/api/form").json()
    assert form["limits"]["max_prompts"] == 20
    assert form["limits"]["max_providers"] == 5
    assert form["scope_options"][0]["value"] == "GIGACHAT_API_PERS"
    assert form["default_provider_ids"] == []
    providers = client.get("/api/providers").json()
    assert providers[0]["editable_fields"] == ["scope", "api_key"]
    assert providers[0]["can_reset"] is True
    assert providers[1]["editable_fields"] == ["api_key"]
    assert providers[1]["can_reset"] is True


def test_form_default_selection_comes_from_python_provider_state(tmp_path):
    store = ConnectionStore(tmp_path, MemorySecrets())
    store.save_connection({"api_key": "ready"}, "deepseek")
    client = TestClient(create_app(store=store, allowed_hosts=["testserver"]))
    assert client.get("/api/form").json()["default_provider_ids"] == ["deepseek"]


def test_check_accepts_raw_form_text_and_returns_ready_report(tmp_path):
    provider = FakeProvider()
    client = TestClient(create_app(provider, store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"]))
    response = client.post("/api/check", json={"brand": " Ромашка ", "prompts_text": "успех\n\nошибка\nдругой", "provider_ids": ["gigachat"]})
    assert response.status_code == 200
    report = response.json()
    assert report["summary"] == {"successful": 2, "failed": 1, "mentioned": 2, "mention_percent": 100,
                                 "visibility_label": "100%", "mentions_label": "2 из 2 успешных ответов", "errors_label": "1 ошибка API"}
    assert [row["prompt"] for row in report["rows"]] == ["успех", "ошибка", "другой"]
    assert report["rows"][1]["provider_name"] == "GigaChat"
    assert report["rows"][1]["status"] == "error"
    assert report["rows"][0]["status"] == "mentioned"
    assert provider.prompts == ["успех", "ошибка", "другой"]
    too_many = client.post("/api/check", json={"brand": "Ромашка", "prompts_text": "\n".join(["вопрос"] * 21), "provider_ids": ["gigachat"]})
    assert too_many.status_code == 400


def test_report_has_no_percent_when_every_call_fails(tmp_path):
    client = TestClient(create_app(FakeProvider(), store=ConnectionStore(tmp_path, MemorySecrets()), allowed_hosts=["testserver"]))
    response = client.post("/api/check", json={"brand": "Ромашка", "prompts_text": "ошибка"})
    assert response.json()["summary"]["mention_percent"] is None
