"""The check endpoint."""

from __future__ import annotations

from tests.fakes import ENDPOINT, MENTION_ANSWER, ProviderFactorySpy


def configure(client, name: str = "Тест") -> str:
    return client.post(
        "/api/providers",
        json={"name": name, "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "k"},
    ).json()["id"]


def test_runs_the_selected_connections(make_client):
    client = make_client(provider_factory=ProviderFactorySpy())
    connection_id = configure(client)

    response = client.post(
        "/api/check",
        json={"brand": " Ромашка ", "domain": " example.ru ", "prompts_text": "первый\n\nвторой",
              "provider_ids": [connection_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["brand"] == "Ромашка"
    assert body["domain"] == "example.ru"
    assert [check["provider_id"] for check in body["checks"]] == [connection_id]
    assert body["summary"] == {
        "successful": 2, "failed": 0, "mentioned": 2, "mention_percent": 100,
        "visibility_label": "100%", "mentions_label": "2 из 2 успешных ответов", "errors_label": "0 ошибок API",
    }
    assert [row["prompt"] for row in body["rows"]] == ["первый", "второй"]
    assert body["rows"][0]["answer"] == MENTION_ANSWER
    assert body["rows"][0]["status"] == "mentioned"


def test_an_invalid_request_never_calls_a_provider(make_client):
    spy = ProviderFactorySpy()
    client = make_client(provider_factory=spy)
    configure(client)

    assert client.post("/api/check", json={"brand": "", "prompts": ["вопрос"]}).status_code == 400
    assert client.post("/api/check", json={"brand": "Ромашка", "prompts_text": "\n".join(["в"] * 21)}).status_code == 400
    assert spy.keys == []


def test_unknown_or_duplicate_selection_is_rejected(make_client):
    spy = ProviderFactorySpy()
    client = make_client(provider_factory=spy)
    connection_id = configure(client)

    for ids in (["missing"], [connection_id, connection_id], [], [connection_id] * 6):
        response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ids})
        assert response.status_code == 400
        assert isinstance(response.json()["detail"], str)
    assert spy.keys == []


def test_a_missing_key_becomes_a_provider_error_row(make_client):
    client = make_client(provider_factory=ProviderFactorySpy())

    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]})

    assert response.status_code == 200
    body = response.json()
    assert body["checks"][0]["summary"] == {"successful": 0, "failed": 1, "mentioned": 0}
    assert body["checks"][0]["results"][0]["error"] == "Добавьте API-ключ в настройках подключения"
    assert body["summary"]["mention_percent"] is None


def test_one_failure_does_not_erase_the_other_connection(make_client):
    client = make_client(provider_factory=ProviderFactorySpy(explode_ids=("gigachat",)))
    client.put("/api/providers/gigachat", json={"api_key": "one"})
    connection_id = configure(client)

    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat", connection_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["checks"][0]["summary"] == {"successful": 0, "failed": 1, "mentioned": 0}
    assert body["checks"][1]["summary"] == {"successful": 1, "failed": 0, "mentioned": 1}
    assert "private path" not in response.text


def test_provider_errors_never_leak_the_key(make_client):
    client = make_client(provider_factory=ProviderFactorySpy())
    client.post(
        "/api/providers",
        json={"name": "Тест", "kind": "openai", "endpoint": ENDPOINT, "model": "m", "api_key": "secret-value"},
    )
    connection_id = client.get("/api/providers").json()[-1]["id"]

    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": [connection_id]},
    )

    assert "secret-value" not in response.text


def test_check_reports_an_unreadable_configuration(client, config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.json").write_text("{", encoding="utf-8")

    response = client.post(
        "/api/check",
        json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ["gigachat"]},
    )

    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
