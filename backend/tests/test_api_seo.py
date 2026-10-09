"""HTTP contract for durable SEO analyses: creation, history, snapshot, rows.

Every collaborator is a fake injected through the container, so the suite proves
the `202` estimate, the safe projections, and the "no paid call inside the HTTP
request or before validation" guarantees without reaching a paid API. The agent
runtime is a fake as well: the graph itself is covered by
`test_service_seo_agents.py`.
"""

from __future__ import annotations

import time

from app.db.search_settings import SearchSettingsRepository
from app.db.seo import SeoRepository
from app.domain.seo import (
    Candidate,
    GeneratedQuery,
    QueryFlags,
    SeoInput,
    normalize_seo_request,
)
from app.service.search import DISABLED_ENGINE
from app.service.seo import LLM_NOT_CONFIGURED
from tests.fakes import (
    ENDPOINT,
    FakeSeoAgentRuntime,
    FakeSeoSettingsService,
    ScriptedSeoGateway,
    SeoProviderFactorySpy,
    tool_calling_settings,
)

SEEDS = ("букет цветов", "доставка цветов", "розы")
QUERY_TEXTS = (
    "купить букет недорого",
    "Ромашка доставка цветов",
    "rival.ru отзывы",
    "как выбрать букет",
    "сравнение конкурентов букеты",
)
SUMMARY = "Итог: сайт виден в Яндексе и упоминается моделями."
MODEL_ANSWER = "Модель советует «Ромашка» и https://example.ru/"
ESTIMATE = {"search_upper": 10, "model_upper": 10, "generated_limit": 7, "connections": 1}
SNAPSHOT_FIELDS = {
    "id", "status", "created_at", "updated_at", "finished_at", "input", "estimate",
    "company_name", "services", "pages", "stages", "agents", "budget", "budget_exhausted",
    "candidates", "queries", "summary", "counters", "readiness", "aggregates",
}
COUNTERS = {
    "queries": 0, "search_rows": 0, "model_rows": 0, "search_errors": 0, "model_errors": 0,
}


def create_provider(client, name: str = "Модель") -> str:
    response = client.post("/api/providers", json={
        "name": name, "kind": "openai", "endpoint": ENDPOINT, "model": "m",
        "api_key": f"{name}-key",
    })
    assert response.status_code == 200
    return response.json()["id"]


def request_body(connection_ids: list[str], **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "url": "https://example.ru/",
        "sphere": "Цветочный магазин",
        "seeds": list(SEEDS),
        "services": ["Букеты", "Доставка"],
        "connection_ids": list(connection_ids),
    }
    body.update(overrides)
    return body


def seed_input(connection_ids: tuple[str, ...] = ("conn-1",)) -> SeoInput:
    return normalize_seo_request(request_body(list(connection_ids)))


def make_repository(settings) -> SeoRepository:
    repository = SeoRepository(settings.config_dir)
    repository.initialize()
    return repository


def run_container(settings, *, gateway=None, spy=None, repository=None,
                  runtime=None, settings_service=None):
    """Override the SEO collaborators with fakes; nothing here reaches a paid API."""
    repository = repository if repository is not None else make_repository(settings)
    return {
        "seo_repository": repository,
        "search_gateway": gateway if gateway is not None else ScriptedSeoGateway(),
        "provider_factory": spy if spy is not None else SeoProviderFactorySpy(),
        "seo_settings_service": (
            settings_service if settings_service is not None else tool_calling_settings()
        ),
        "seo_agent_runtime": (
            runtime if runtime is not None else FakeSeoAgentRuntime(repository)
        ),
    }


def wait_terminal(client, analysis_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/seo/analyses/{analysis_id}").json()
        if snapshot["status"] != "running":
            return snapshot
        time.sleep(0.01)
    raise AssertionError("the SEO analysis did not reach a terminal state")


def seed_analysis(repository: SeoRepository) -> str:
    """Write one completed analysis with one saved model answer and one Yandex row."""
    analysis_id = repository.create_analysis(seed_input(), ESTIMATE)
    repository.save_site_facts(
        analysis_id, "Ромашка", ("Букеты", "Доставка"),
        (("https://example.ru/", "Ромашка — букеты"),),
    )
    repository.replace_candidates(analysis_id, (
        Candidate(
            host="rival.ru", title="Соперник — букеты", occurrences=2,
            average_position=3.0, seed_indexes=(0, 1), recurring=True,
        ),
    ))
    repository.replace_queries(analysis_id, (
        GeneratedQuery(
            text=QUERY_TEXTS[0], category="commercial", service="Букеты",
            flags=QueryFlags(
                mentions_company_name=False, mentions_company_host=False,
                mentions_candidate_host=False, branded=False,
            ),
        ),
    ))
    repository.save_search_row(
        analysis_id, 0, status="found", operation_id="yandex-operation-secret",
        site_position=2, site_url="https://example.ru/",
    )
    repository.save_model_row(
        analysis_id, "conn-1", "Модель", 0, status="found", answer=MODEL_ANSWER,
        name_mentioned=True, host_mentioned=True,
    )
    repository.save_summary(analysis_id, "Итоговое резюме")
    repository.update_stage(analysis_id, 6, "done", counters={"report": 1})
    repository.finish_analysis(analysis_id)
    return analysis_id


# -- creation -----------------------------------------------------------------


def test_create_answers_202_with_the_upper_estimate_and_finishes_in_the_background(
    make_client, settings,
):
    repository = make_repository(settings)
    gateway = ScriptedSeoGateway()
    spy = SeoProviderFactorySpy()
    runtime = FakeSeoAgentRuntime(repository)
    with make_client(**run_container(
        settings, gateway=gateway, spy=spy, repository=repository, runtime=runtime,
    )) as client:
        first = create_provider(client, "Модель 1")
        second = create_provider(client, "Модель 2")
        created = client.post("/api/seo/analyses", json=request_body([first, second]))

        assert created.status_code == 202
        body = created.json()
        assert set(body) == {"id", "status", "estimate"}
        assert body["status"] == "running"
        assert body["estimate"] == {
            "search_upper": 10, "model_upper": 10, "generated_limit": 7, "connections": 2,
            # Both connections answer in text mode, so no DeepSeek search is paid for.
            "deepseek_search_upper": 0,
        }

        snapshot = wait_terminal(client, body["id"])
        assert snapshot["status"] == "completed"
        # The graph is the only paid work of a run, and the HTTP request never
        # waits for it: the answer above came back while the analysis ran.
        assert runtime.runs[0][0] == body["id"]
        assert runtime.runs[0][1].connection_ids == (first, second)
        assert gateway.submitted == []
        assert spy.keys == []


def test_invalid_input_is_rejected_before_any_paid_call(make_client, settings):
    gateway = ScriptedSeoGateway()
    spy = SeoProviderFactorySpy()
    settings_service = tool_calling_settings()
    unknown = request_body(["нет такого"])
    with make_client(**run_container(
        settings, gateway=gateway, spy=spy, settings_service=settings_service,
    )) as client:
        provider = create_provider(client)
        for payload in (
            request_body([provider], seeds=["один", "два"]),
            request_body([provider], services=[]),
            request_body([provider], sphere=""),
            request_body([provider], url=None),
            request_body([provider], unknown_field="value"),
            unknown,
        ):
            response = client.post("/api/seo/analyses", json=payload)
            assert response.status_code == 400, payload
            assert isinstance(response.json()["detail"], str)

        history = client.get("/api/seo/analyses").json()
        assert history == {"items": [], "next_cursor": None}

    assert gateway.submitted == []
    assert spy.keys == []
    # A refused request never reached the model probe either.
    assert settings_service.model.steps == []


def test_disabled_yandex_is_rejected_before_any_paid_call(make_client, settings, secrets):
    search_repository = SearchSettingsRepository(
        settings.config_dir, secrets, env_api_key=None, env_folder_id=None,
        service_name=settings.service_name,
    )
    search_repository.update({"enabled": False})
    gateway = ScriptedSeoGateway()
    spy = SeoProviderFactorySpy()
    settings_service = tool_calling_settings()
    with make_client(
        search_settings_repository=search_repository,
        **run_container(settings, gateway=gateway, spy=spy, settings_service=settings_service),
    ) as client:
        provider = create_provider(client)
        response = client.post("/api/seo/analyses", json=request_body([provider]))

    assert response.status_code == 400
    assert response.json() == {"detail": DISABLED_ENGINE}
    assert gateway.submitted == []
    assert spy.keys == []
    assert settings_service.model.steps == []


def test_a_missing_llm_configuration_is_rejected_before_any_paid_call(make_client, settings):
    gateway = ScriptedSeoGateway()
    spy = SeoProviderFactorySpy()
    overrides = run_container(
        settings, gateway=gateway, spy=spy, settings_service=FakeSeoSettingsService(None),
    )
    with make_client(**overrides) as client:
        provider = create_provider(client)
        response = client.post("/api/seo/analyses", json=request_body([provider]))

    assert response.status_code == 400
    assert response.json() == {"detail": LLM_NOT_CONFIGURED}
    assert gateway.submitted == []
    assert spy.keys == []


# -- history ------------------------------------------------------------------


def test_history_is_paginated_newest_first(make_client, settings):
    repository = make_repository(settings)
    created = [repository.create_analysis(seed_input(), ESTIMATE) for _ in range(21)]
    with make_client(seo_repository=repository) as client:
        first = client.get("/api/seo/analyses")
        assert first.status_code == 200
        page = first.json()
        assert len(page["items"]) == 20
        assert page["next_cursor"]
        assert page["items"][0]["id"] == created[-1]
        assert page["items"][0]["counters"] == COUNTERS
        assert set(page["items"][0]) == {
            "id", "created_at", "finished_at", "status", "sphere", "host",
            "company_name", "counters",
        }

        second = client.get("/api/seo/analyses", params={"cursor": page["next_cursor"]})
        assert second.status_code == 200
        assert len(second.json()["items"]) == 1
        assert second.json()["next_cursor"] is None
        assert client.get("/api/seo/analyses", params={"cursor": "!!!"}).status_code == 400
        assert client.get("/api/seo/analyses", params={"cursor": "a"}).status_code == 400


# -- snapshot -----------------------------------------------------------------


def test_snapshot_projection_hides_model_answers_and_operation_ids(make_client, settings):
    repository = make_repository(settings)
    analysis_id = seed_analysis(repository)
    with make_client(seo_repository=repository) as client:
        response = client.get(f"/api/seo/analyses/{analysis_id}")

    assert response.status_code == 200
    snapshot = response.json()
    assert set(snapshot) == SNAPSHOT_FIELDS
    assert snapshot["status"] == "completed"
    assert snapshot["finished_at"] is not None
    assert [stage["stage"] for stage in snapshot["stages"]] == [1, 2, 3, 4, 5, 6]
    assert snapshot["input"]["seeds"] == list(SEEDS)
    assert snapshot["company_name"] == "Ромашка"
    assert snapshot["pages"] == [{"url": "https://example.ru/", "title": "Ромашка — букеты"}]
    assert snapshot["candidates"][0]["host"] == "rival.ru"
    assert snapshot["queries"][0]["flags"]["branded"] is False
    assert snapshot["counters"] == {
        "queries": 1, "search_rows": 1, "model_rows": 1,
        "search_errors": 0, "model_errors": 0,
    }
    assert snapshot["readiness"]["report_ready"] is True
    assert set(snapshot["aggregates"]) == {
        "site", "competitors", "categories", "services", "counts",
    }
    assert snapshot["aggregates"]["counts"] == snapshot["counters"]
    assert snapshot["aggregates"]["site"]["search"]["overall"]["share"] == 1.0
    assert snapshot["aggregates"]["site"]["ai"]["conn-1"]["combined"]["share"] == 1.0
    position = snapshot["aggregates"]["site"]["ai"]["conn-1"]["position"]
    assert set(position) == {"first", "early", "late", "absent", "ahead"}
    assert position["first"] == {
        "denominator": 1, "successes": 1, "share": 1.0, "average_position": None,
    }
    assert position["ahead"]["denominator"] == 0
    assert position["ahead"]["share"] is None
    assert snapshot["aggregates"]["site"]["ai"]["conn-1"]["branded"]["position"] is None
    assert snapshot["aggregates"]["site"]["ai"]["conn-1"]["unbranded"]["position"] is None

    assert MODEL_ANSWER not in response.text
    assert "yandex-operation-secret" not in response.text
    assert "operation_id" not in response.text


def test_snapshot_of_an_unfinished_analysis_has_no_answers(make_client, settings):
    repository = make_repository(settings)
    analysis_id = repository.create_analysis(seed_input(), ESTIMATE)
    with make_client(seo_repository=repository) as client:
        response = client.get(f"/api/seo/analyses/{analysis_id}")

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["status"] in {"running", "interrupted"}
    assert snapshot["aggregates"]["site"]["search"]["overall"]["share"] is None
    assert snapshot["aggregates"]["site"]["search"]["overall"]["denominator"] == 0


# -- rows ---------------------------------------------------------------------


def test_rows_are_filtered_and_paginated_without_operation_ids(make_client, settings):
    repository = make_repository(settings)
    analysis_id = repository.create_analysis(seed_input(), ESTIMATE)
    repository.replace_queries(analysis_id, tuple(
        GeneratedQuery(
            text=f"запрос {index}", category="commercial", service="Букеты",
            flags=QueryFlags(
                mentions_company_name=False, mentions_company_host=False,
                mentions_candidate_host=False, branded=False,
            ),
        )
        for index in range(3)
    ))
    for index in range(3):
        repository.save_search_row(
            analysis_id, index, status="found", operation_id=f"yandex-operation-{index}",
            site_position=index + 1, site_url=f"https://example.ru/{index}",
        )
    for index in range(51):
        repository.save_model_row(
            analysis_id, f"conn-{index:02d}", "Модель", 0, status="found",
            answer=f"ответ {index}", name_mentioned=True, host_mentioned=False,
        )

    with make_client(seo_repository=repository) as client:
        first = client.get(f"/api/seo/analyses/{analysis_id}/rows", params={"kind": "model"})
        assert first.status_code == 200
        page = first.json()
        assert len(page["items"]) == 50
        assert page["next_cursor"]
        assert page["items"][0] == {
            "query_index": 0, "connection_id": "conn-00", "provider_name": "Модель",
            "status": "found", "answer": "ответ 0", "name_mentioned": True,
            "host_mentioned": False, "error": None, "query": "запрос 0",
            "category": "commercial", "service": "Букеты",
            # A text-mode row carries no search evidence of its own.
            "answer_mode": "text", "search_status": "not_requested",
            "search_results": [], "citations": [], "model": None, "search_calls": None,
        }

        second = client.get(
            f"/api/seo/analyses/{analysis_id}/rows",
            params={"kind": "model", "cursor": page["next_cursor"]},
        )
        assert second.status_code == 200
        assert [row["connection_id"] for row in second.json()["items"]] == ["conn-50"]
        assert second.json()["next_cursor"] is None

        search = client.get(f"/api/seo/analyses/{analysis_id}/rows", params={"kind": "search"})
        assert search.status_code == 200
        assert [row["site_position"] for row in search.json()["items"]] == [1, 2, 3]
        assert search.json()["items"][0]["query"] == "запрос 0"
        assert search.json()["next_cursor"] is None
        assert "operation_id" not in search.text
        assert "yandex-operation-0" not in search.text

        assert client.get(
            f"/api/seo/analyses/{analysis_id}/rows", params={"kind": "other"},
        ).status_code == 400
        assert client.get(
            f"/api/seo/analyses/{analysis_id}/rows", params={"kind": "search", "cursor": "!!!"},
        ).status_code == 400
        assert client.get("/api/seo/analyses/missing/rows", params={"kind": "model"}).status_code == 404


# -- cancel and delete --------------------------------------------------------


def test_cancel_stops_a_running_analysis_and_terminal_states_are_deleted(make_client, settings):
    repository = make_repository(settings)
    runtime = FakeSeoAgentRuntime(repository, mode="hold")
    with make_client(**run_container(settings, repository=repository, runtime=runtime)) as client:
        provider = create_provider(client)
        created = client.post("/api/seo/analyses", json=request_body([provider]))
        analysis_id = created.json()["id"]

        conflict = client.delete(f"/api/seo/analyses/{analysis_id}")
        assert conflict.status_code == 409
        assert isinstance(conflict.json()["detail"], str)

        cancelled = client.post(f"/api/seo/analyses/{analysis_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["finished_at"] is not None
        assert runtime.cancels == [analysis_id]
        # Cancellation is final: the analysis can never be cancelled again.
        assert client.post(f"/api/seo/analyses/{analysis_id}/cancel").status_code == 409

        assert client.delete(f"/api/seo/analyses/{analysis_id}").status_code == 204
        assert client.get(f"/api/seo/analyses/{analysis_id}").status_code == 404


def test_only_terminal_analyses_can_be_deleted(make_client, settings):
    repository = make_repository(settings)
    analysis_id = seed_analysis(repository)
    with make_client(seo_repository=repository) as client:
        assert client.delete(f"/api/seo/analyses/{analysis_id}").status_code == 204
        assert client.get(f"/api/seo/analyses/{analysis_id}").status_code == 404
        assert client.delete(f"/api/seo/analyses/{analysis_id}").status_code == 404
        assert client.post(f"/api/seo/analyses/{analysis_id}/cancel").status_code == 404


def test_unknown_ids_and_the_api_prefix(make_client, settings):
    with make_client(seo_repository=make_repository(settings)) as client:
        assert client.get("/api/seo/analyses/missing").status_code == 404
        assert client.delete("/api/seo/analyses/missing").status_code == 404
        assert client.post("/api/seo/analyses/missing/cancel").status_code == 404
        assert client.get("/seo/analyses").status_code == 404
        assert client.get("/api/seo/analyses").status_code == 200


def test_trace_endpoint_serves_steps_without_secrets(make_client, settings):
    repository = make_repository(settings)
    analysis_id = seed_analysis(repository)
    repository.append_step(
        analysis_id, "supervisor", "model", "supervisor", status="running",
    )
    repository.append_step(
        analysis_id, "site", "tool", "fetch_site",
        arguments={"max_pages": 2}, result_summary='{"used_pages":1}', status="done",
    )
    repository.append_step(
        analysis_id, "site", "tool", "save_site_facts",
        arguments={"company_name": "Ромашка"}, result_summary='{"status":"saved"}',
        status="done",
    )

    with make_client(seo_repository=repository) as client:
        response = client.get(f"/api/seo/analyses/{analysis_id}/trace")

    assert response.status_code == 200
    page = response.json()
    assert page["next_cursor"] is None
    assert [item["step_index"] for item in page["items"]] == [1, 2, 3]
    assert [item["agent"] for item in page["items"]] == ["supervisor", "site", "site"]
    assert [item["name"] for item in page["items"]] == ["supervisor", "fetch_site", "save_site_facts"]
    assert page["items"][1]["arguments"] == {"max_pages": 2}
    assert set(page["items"][0]) == {
        "step_index", "agent", "kind", "name", "arguments", "result_summary",
        "status", "error", "created_at",
    }
    assert "yandex-operation-secret" not in response.text
    assert MODEL_ANSWER not in response.text

    with make_client(seo_repository=repository) as client:
        assert client.get(f"/api/seo/analyses/{analysis_id}/trace?cursor=%%%").status_code == 400
        assert client.get("/api/seo/analyses/unknown-id/trace").status_code == 404
