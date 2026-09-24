"""The check endpoint."""

from __future__ import annotations

from tests.fakes import ENDPOINT, MENTION_ANSWER, FakeProvider, ProviderFactorySpy


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


def test_models_share_a_key_but_are_checked_separately(make_client):
    calls = []

    def factory(connection, key):
        calls.append((connection.id, connection.model, connection.endpoint, key))
        return FakeProvider(connection.id)

    client = make_client(provider_factory=factory)
    group = client.post("/api/providers/settings", json={
        "name": "Demo", "endpoint": ENDPOINT, "api_key": "shared-secret",
        "models": [{"model": "api-a", "name": "A"}, {"model": "api-b", "name": "B"}],
    }).json()
    ids = [model["id"] for model in group["models"]]

    choices = [item for item in client.get("/api/providers").json() if item["id"] in ids]
    assert [item["name"] for item in choices] == ["Demo · A", "Demo · B"]
    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ids})

    assert response.status_code == 200
    assert [item["provider_id"] for item in response.json()["checks"]] == ids
    assert calls == [(ids[0], "api-a", ENDPOINT, "shared-secret"), (ids[1], "api-b", ENDPOINT, "shared-secret")]


def test_removed_model_is_rejected_before_any_api_call(make_client):
    spy = ProviderFactorySpy()
    client = make_client(provider_factory=spy)
    group = client.post("/api/providers/settings", json={
        "name": "Demo", "endpoint": ENDPOINT, "api_key": "shared-secret",
        "models": [{"model": "api-a", "name": "A"}, {"model": "api-b", "name": "B"}],
    }).json()
    removed = group["models"][1]["id"]
    client.put(f"/api/providers/settings/{group['id']}", json={
        "name": "Demo", "endpoint": ENDPOINT, "models": [group["models"][0]],
    })

    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": [removed]})
    assert response.status_code == 400
    assert spy.keys == []


def test_one_model_failure_keeps_its_sibling_result(make_client):
    client = make_client(provider_factory=ProviderFactorySpy())
    group = client.post("/api/providers/settings", json={
        "name": "Demo", "endpoint": ENDPOINT, "api_key": "shared-secret",
        "models": [{"model": "api-a", "name": "A"}, {"model": "api-b", "name": "B"}],
    }).json()
    ids = [model["id"] for model in group["models"]]
    spy = ProviderFactorySpy(explode_ids=(ids[0],))
    client = make_client(provider_factory=spy)

    response = client.post("/api/check", json={"brand": "Ромашка", "prompts": ["вопрос"], "provider_ids": ids})
    assert response.status_code == 200
    assert [item["summary"]["successful"] for item in response.json()["checks"]] == [0, 1]
