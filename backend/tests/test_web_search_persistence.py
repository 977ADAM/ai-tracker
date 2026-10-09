"""Modes, answer evidence and frozen run settings survive persistence."""

import sqlite3

import pytest
from app.core.errors import ValidationError
from app.db.chat import ChatRepository
from app.db.connections import ConnectionRepository
from app.db.runs import RunRepository
from app.db.seo import SeoRepository
from app.domain.provider_groups import build_group
from app.domain.seo_answer import (
    Citation,
    SearchResult,
    SeoAnswer,
    SeoConnectionSnapshot,
)

from tests.fakes import MemorySecrets
from tests.test_db_seo import seo_input


def group_payload(**updates):
    return {"name": "DeepSeek", "endpoint": "https://api.deepseek.com/chat/completions",
            "models": [{"model": "deepseek-flash", "name": "Flash"}], **updates}


def test_search_mode_survives_group_and_connection_projection(tmp_path):
    repo = ConnectionRepository(tmp_path, MemorySecrets())
    group = build_group(group_payload(answer_mode="deepseek_web"))
    repo.save_group(group, "secret")
    assert repo.groups()[0].answer_mode == "deepseek_web"
    assert repo.all()[0].answer_mode == "deepseek_web"
    assert "secret" not in repo.path.read_text()


@pytest.mark.parametrize("updates", [
    {"answer_mode": "unknown"},
    {"answer_mode": "deepseek_web", "endpoint": "https://other.com/chat/completions"},
    {"answer_mode": "deepseek_web", "endpoint": "https://api.deepseek.com/other/chat/completions"},
])
def test_invalid_search_modes_are_rejected(updates):
    with pytest.raises(ValidationError):
        build_group(group_payload(**updates))


def test_existing_group_defaults_to_text(tmp_path):
    repo = ConnectionRepository(tmp_path, MemorySecrets())
    repo.save_group(build_group(group_payload()))
    assert repo.all()[0].answer_mode == "text"


def test_answer_sources_round_trip_and_status_update_preserves_sources(tmp_path):
    repo = SeoRepository(tmp_path); repo.initialize()
    run = repo.create_analysis(seo_input(), {})
    evidence = SeoAnswer("Компания", "deepseek_web", "completed",
                         (SearchResult("https://example.ru/", "Сайт"),),
                         (Citation("https://example.ru/", "Сайт", "Факт", 0, 1),),
                         "deepseek-flash", 1)
    repo.save_model_row(run, "chatgpt", "Model", 0, status="found", answer="Компания", seo_answer=evidence)
    repo.save_model_row(run, "chatgpt", "Model", 0, status="found")
    row = repo.rows_page(run, "model")["items"][0]
    assert row["search_status"] == "completed"
    assert row["citations"][0]["url"] == "https://example.ru/"
    assert row["search_results"][0]["title"] == "Сайт"
    assert row["model"] == "deepseek-flash"
    assert row["answer"] == "Компания"


def test_snapshots_survive_restart_without_secrets(tmp_path):
    repo = SeoRepository(tmp_path); repo.initialize()
    frozen = SeoConnectionSnapshot("chatgpt", "Model", "openai", "https://api.deepseek.com/chat/completions",
                                   "deepseek-flash", "deepseek_web", False)
    run = repo.create_analysis(seo_input(), {}, connection_snapshots=(frozen,))
    second = SeoRepository(tmp_path); second.initialize()
    assert second.connection_snapshots(run) == (frozen,)


def test_version_six_is_accepted_by_all_owners_and_old_rows_have_no_search(tmp_path):
    repo = SeoRepository(tmp_path); repo.initialize()
    run = repo.create_analysis(seo_input(), {})
    repo.save_model_row(run, "chatgpt", "Model", 0, status="absent", answer="Нет")
    for owner in (RunRepository(tmp_path), ChatRepository(tmp_path), SeoRepository(tmp_path)):
        owner.initialize()
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
    row = repo.rows_page(run, "model")["items"][0]
    assert row["search_status"] == "not_requested"
    assert row["citations"] == []
