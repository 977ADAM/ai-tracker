"""The run uses frozen settings and persists structured search evidence."""

import json
from dataclasses import asdict, replace

import pytest

from app.domain.seo_answer import (
    Citation,
    SearchResult,
    SeoAnswer,
    SeoConnectionSnapshot,
)
from tests.test_service_seo import make_harness as make_service
from tests.test_service_seo import payload as service_payload
from tests.test_service_seo_tools import make_env, ready


@pytest.mark.anyio
async def test_search_answer_is_persisted_and_not_paid_twice(tmp_path, repository, settings):
    calls = []
    class Provider:
        def answer(self, prompt):
            calls.append(prompt)
            return SeoAnswer("Ромашка", "deepseek_web", "completed",
                (SearchResult("https://example.ru/", "Сайт"),),
                (Citation("https://example.ru/", None, None, 0, 1),), "deepseek-flash", 1)
        def close(self):
            pass
    env = make_env(tmp_path, repository, settings, seo_answer_factory=lambda snapshot, key: Provider())
    await ready(env)
    await env.toolbox.call("ask_models", {})
    count = len(calls)
    await env.toolbox.call("ask_models", {})
    assert len(calls) == count
    row = env.repository.rows_page(env.analysis_id, "model")["items"][0]
    assert row["search_status"] == "completed"
    assert row["name_mentioned"] is True
    assert row["citations"][0]["url"] == "https://example.ru/"


@pytest.mark.anyio
async def test_toolbox_uses_frozen_model_instead_of_current_settings(tmp_path, repository, settings):
    seen = []
    class Provider:
        def answer(self, prompt):
            return SeoAnswer("Нет", "deepseek_web", "completed", (), (), "frozen-model", 1)
        def close(self):
            pass
    def factory(snapshot, key):
        seen.append(snapshot)
        return Provider()
    env = make_env(tmp_path, repository, settings, seo_answer_factory=factory)
    frozen = SeoConnectionSnapshot("openai", "Frozen", "openai", "https://api.deepseek.com/chat/completions", "frozen-model", "deepseek_web", False)
    with env.repository._connection(write=True) as db:
        db.execute("UPDATE seo_analyses SET connection_snapshots=? WHERE id=?", (json.dumps([asdict(frozen)]), env.analysis_id))
    await ready(env)
    await env.toolbox.call("ask_models", {})
    assert seen and all(item == frozen for item in seen)


@pytest.mark.anyio
async def test_legacy_analysis_without_snapshot_remains_text(tmp_path, repository, settings, monkeypatch):
    seen = []
    class Provider:
        def answer(self, prompt):
            return SeoAnswer("Нет", "text", "not_requested", (), (), "model", None)
        def close(self):
            pass
    def factory(snapshot, key):
        seen.append(snapshot)
        return Provider()
    env = make_env(tmp_path, repository, settings, seo_answer_factory=factory)
    current = env.connections.require("openai")
    monkeypatch.setattr(env.connections, "require", lambda _id: replace(current, answer_mode="deepseek_web"))
    await ready(env)
    await env.toolbox.call("ask_models", {})
    assert seen and all(item.answer_mode == "text" for item in seen)


@pytest.mark.anyio
async def test_service_freezes_settings_at_start(tmp_path, repository, settings):
    env = make_service(tmp_path, repository, settings)
    created = await env.service.start(service_payload())
    frozen = env.repository.connection_snapshots(created["id"])
    assert frozen[0].connection_id == "openai"
    assert frozen[0].model == env.connections.require("openai").model
    assert created["estimate"]["deepseek_search_upper"] == 0
    await env.service.close()
