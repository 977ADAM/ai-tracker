from fastapi.testclient import TestClient

from ai_tracker.gigachat import ProviderError
from ai_tracker.web import create_app


class FakeProvider:
    def __init__(self):
        self.prompts = []

    def answer(self, prompt):
        self.prompts.append(prompt)
        if prompt == "ошибка":
            raise ProviderError("Сервис временно недоступен")
        return "Ромашка рекомендует этот вариант"


def test_returns_answers_and_summary():
    provider = FakeProvider()
    response = TestClient(create_app(provider)).post(
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


def test_partial_failure_is_not_negative_mention():
    response = TestClient(create_app(FakeProvider())).post(
        "/api/check", json={"brand": "Ромашка", "prompts": ["успех", "ошибка"]}
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"successful": 1, "failed": 1, "mentioned": 1}
    assert response.json()["results"][1] == {
        "prompt": "ошибка", "answer": None, "mentioned": None, "error": "Сервис временно недоступен"
    }


def test_invalid_request_does_not_call_provider():
    provider = FakeProvider()
    response = TestClient(create_app(provider)).post(
        "/api/check", json={"brand": "", "prompts": ["вопрос"]}
    )
    assert response.status_code == 400
    assert provider.prompts == []


def test_missing_credentials_is_service_error(monkeypatch):
    monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)
    response = TestClient(create_app()).post(
        "/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"]}
    )
    assert response.status_code == 503
    assert "GIGACHAT_AUTH_KEY" in response.json()["detail"]
