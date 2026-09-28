"""Pure tool rules: budget ceilings, schemas, per-agent subsets, and arguments.

Nothing here touches a provider or a database: the module owns the server-side
refusals that no prompt can talk the model out of.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import AppError
from app.domain.seo import GENERATED_QUERY_LIMIT, MIN_GENERATED_QUERIES
from app.domain.seo_llm import ToolSchema
from app.domain.seo_tools import (
    AGENT_TOOLS,
    AGENTS,
    BUDGET_EXHAUSTED,
    CHECK_TOOLS,
    COMPETITOR_TOOLS,
    LLM_CALL_TIMEOUT,
    MAX_FETCH_PAGES,
    MAX_SEARCH_REQUESTS,
    MAX_SPECIALIST_TURNS,
    MAX_SUPERVISOR_HANDOFFS,
    MAX_TOOL_CALLS,
    QUERY_TOOLS,
    REPORT_TOOLS,
    SEARCH_REGION,
    SITE_TOOLS,
    SPECIALIST_AGENTS,
    SUPERVISOR_TOOLS,
    TOOL_ARGUMENTS,
    TOOL_SCHEMAS,
    BudgetExceeded,
    SeoBudget,
    ToolRejected,
    schema_for,
    tools_for,
    validate_arguments,
)

ALL_TOOL_NAMES = tuple(TOOL_SCHEMAS)


def query(text: str, category: str = "commercial", service: str = "") -> dict[str, object]:
    return {"query": text, "category": category, "service": service}


def test_the_agreed_limits_are_the_ones_the_run_uses():
    assert GENERATED_QUERY_LIMIT == 40
    assert MIN_GENERATED_QUERIES == 5
    assert MAX_SEARCH_REQUESTS == 43
    assert MAX_FETCH_PAGES == 20
    assert MAX_SUPERVISOR_HANDOFFS == 15
    assert MAX_SPECIALIST_TURNS == 20
    assert MAX_TOOL_CALLS == 120
    assert LLM_CALL_TIMEOUT == 120.0
    assert SEARCH_REGION == 225
    assert AGENTS == ("supervisor", "site", "competitors", "queries", "checks", "report")
    assert SPECIALIST_AGENTS == ("site", "competitors", "queries", "checks", "report")


def test_every_tool_schema_is_self_consistent_and_json_serializable():
    assert len(TOOL_SCHEMAS) == len(TOOL_ARGUMENTS) == 16
    for name, schema in TOOL_SCHEMAS.items():
        assert isinstance(schema, ToolSchema)
        assert schema.name == name
        assert schema.description.strip()
        # A schema that cannot be sent to a provider would break every call.
        json.dumps(schema.parameters, ensure_ascii=False)
        assert schema.parameters["type"] == "object"
        assert schema.parameters["additionalProperties"] is False
        properties = schema.parameters["properties"]
        assert set(properties) == {argument.name for argument in TOOL_ARGUMENTS[name]}
        for argument in TOOL_ARGUMENTS[name]:
            assert properties[argument.name]["description"].strip()
        required = set(schema.parameters.get("required", ()))
        assert required == {argument.name for argument in TOOL_ARGUMENTS[name] if argument.required}
        assert required <= set(properties)
    assert schema_for("fetch_site") == TOOL_SCHEMAS["fetch_site"]
    with pytest.raises(ToolRejected):
        schema_for("неизвестный")


def test_each_agent_sees_exactly_its_own_tools():
    subsets = {
        "supervisor": SUPERVISOR_TOOLS,
        "site": SITE_TOOLS,
        "competitors": COMPETITOR_TOOLS,
        "queries": QUERY_TOOLS,
        "checks": CHECK_TOOLS,
        "report": REPORT_TOOLS,
    }
    assert set(AGENT_TOOLS) == set(AGENTS) == set(subsets)
    seen: list[str] = []
    for agent, names in subsets.items():
        tools = tools_for(agent)
        assert [tool.name for tool in tools] == list(names)
        assert all(tool in TOOL_SCHEMAS.values() for tool in tools)
        seen.extend(names)
    # Every tool belongs to exactly one agent: a specialist can never reach a
    # tool of another specialist or the supervisor's control tools.
    assert sorted(seen) == sorted(ALL_TOOL_NAMES)
    assert len(seen) == len(set(seen))
    assert set(SITE_TOOLS) & set(COMPETITOR_TOOLS) == set()
    assert "handoff_to" in SUPERVISOR_TOOLS and "finish_run" in SUPERVISOR_TOOLS
    assert "handoff_to" not in SITE_TOOLS and "save_queries" not in CHECK_TOOLS
    with pytest.raises(ToolRejected):
        tools_for("неизвестный агент")


def test_validate_arguments_normalizes_a_valid_call():
    assert validate_arguments("fetch_site", {}) == {}
    assert validate_arguments("fetch_site", {"max_pages": 5}) == {"max_pages": 5}
    assert validate_arguments("read_page", {"url": "  https://example.ru/x  "}) == {
        "url": "https://example.ru/x",
    }
    assert validate_arguments(
        "save_site_facts", {"company_name": " Ромашка ", "services": [" Букеты ", "Доставка"]},
    ) == {"company_name": "Ромашка", "services": ["Букеты", "Доставка"]}
    assert validate_arguments("save_site_facts", {"company_name": "", "services": []}) == {
        "company_name": "", "services": [],
    }
    assert validate_arguments("yandex_search", {"query": " букеты "}) == {"query": "букеты"}
    assert validate_arguments("save_candidates", {"candidates": []}) == {"candidates": []}
    assert validate_arguments(
        "save_candidates",
        {"candidates": [{"host": "rival.ru", "note": "соперник"}, {"host": "other.ru"}]},
    ) == {"candidates": [{"host": "rival.ru", "note": "соперник"}, {"host": "other.ru", "note": ""}]}
    assert validate_arguments("list_seed_results", None) == {}
    assert validate_arguments("save_queries", {"queries": [query("купить букет")]}) == {
        "queries": [{"query": "купить букет", "category": "commercial", "service": ""}],
    }
    assert validate_arguments("search_many", {"queries": ["раз", "два"]}) == {"queries": ["раз", "два"]}
    assert validate_arguments("ask_models", {"connection_ids": ["a", "b"]}) == {
        "connection_ids": ["a", "b"],
    }
    assert validate_arguments("handoff_to", {"agent": "site", "reason": "нужны страницы"}) == {
        "agent": "site", "reason": "нужны страницы",
    }
    assert validate_arguments("finish_run", {"reason": ""}) == {"reason": ""}


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("неизвестный", {}),
        ("fetch_site", {"max_pages": "пять"}),
        ("fetch_site", {"max_pages": 0}),
        ("fetch_site", {"max_pages": MAX_FETCH_PAGES + 1}),
        ("fetch_site", {"max_pages": True}),
        ("fetch_site", {"url": "https://example.ru/"}),
        ("fetch_site", "не объект"),
        ("read_page", {}),
        ("read_page", {"url": ""}),
        ("read_page", {"url": "   "}),
        ("read_page", {"url": "x" * 2049}),
        ("read_page", {"url": "https://example.ru/", "extra": 1}),
        ("save_site_facts", {"company_name": "Ромашка"}),
        ("save_site_facts", {"services": ["Букеты"]}),
        ("save_site_facts", {"company_name": 42, "services": []}),
        ("save_site_facts", {"company_name": "Ромашка", "services": "Букеты"}),
        ("save_site_facts", {"company_name": "Ромашка", "services": [""]}),
        ("save_site_facts", {"company_name": "Ромашка", "services": ["x" * 101]}),
        ("save_site_facts", {"company_name": "Ромашка", "services": ["a"] * 21}),
        ("yandex_search", {}),
        ("yandex_search", {"query": ""}),
        ("yandex_search", {"query": "x" * 401}),
        ("yandex_search", {"query": " ".join(["слово"] * 41)}),
        ("list_seed_results", {"extra": 1}),
        ("save_candidates", {}),
        ("save_candidates", {"candidates": "rival.ru"}),
        ("save_candidates", {"candidates": [{"note": "нет хоста"}]}),
        ("save_candidates", {"candidates": [{"host": ""}]}),
        ("save_candidates", {"candidates": [{"host": "rival.ru", "other": 1}]}),
        ("save_candidates", {"candidates": [{"host": "rival.ru"}, {"host": "RIVAL.RU"}]}),
        ("save_queries", {}),
        ("save_queries", {"queries": []}),
        ("save_queries", {"queries": "запрос"}),
        ("save_queries", {"queries": [{"query": "раз"}]}),
        ("save_queries", {"queries": [{"query": "раз", "category": 42}]}),
        ("save_queries", {"queries": [query("")]}),
        ("save_queries", {"queries": [{"query": "раз", "category": "commercial", "extra": 1}]}),
        ("save_queries", {"queries": [{"query": "раз", "category": "commercial", "service": 42}]}),
        ("save_queries", {"queries": [query(f"запрос {index}") for index in range(41)]}),
        ("search_many", {"queries": []}),
        ("search_many", {"queries": [""]}),
        ("search_many", {"queries": ["раз"] * 41}),
        ("ask_models", {"connection_ids": []}),
        ("ask_models", {"connection_ids": ["a", "a"]}),
        ("ask_models", {"connection_ids": ["a"] * 6}),
        ("ask_models", {"connection_ids": [42]}),
        ("read_metrics", {"extra": 1}),
        ("save_report", {"summary": "сводка"}),
        ("save_report", {"summary": "", "recommendations": "выводы"}),
        ("save_report", {"summary": 42, "recommendations": "выводы"}),
        ("handoff_to", {"agent": "site"}),
        ("handoff_to", {"agent": ""}),
        ("handoff_to", {"agent": "супервизор", "reason": 42}),
        ("finish_run", {"reason": "x" * 501}),
        ("read_status", {"extra": 1}),
    ],
)
def test_rejects_unusable_arguments_and_unknown_tools(name, arguments):
    with pytest.raises(ToolRejected):
        validate_arguments(name, arguments)


def test_a_rejection_is_a_safe_app_error():
    with pytest.raises(AppError):
        validate_arguments("неизвестный", {})
    budget = SeoBudget(max_pages=0)
    with pytest.raises(AppError):
        budget.spend_pages()


def test_budget_spend_returns_a_new_budget_without_mutating_the_old_one():
    first = SeoBudget.for_connections(1)
    second = first.spend_pages(2).spend_search().spend_model_answer(3).spend_tool_call().spend_handoff()

    assert first == SeoBudget.for_connections(1)
    assert (first.pages, first.searches, first.model_answers, first.tool_calls, first.handoffs) == (0, 0, 0, 0, 0)
    assert (second.pages, second.searches, second.model_answers) == (2, 1, 3)
    assert (second.tool_calls, second.handoffs) == (1, 1)
    assert second.max_model_answers == GENERATED_QUERY_LIMIT


def test_every_budget_raises_budget_exceeded_at_its_cap():
    pages = SeoBudget(max_pages=2, max_searches=0, max_model_answers=0, max_tool_calls=0, max_handoffs=0)
    spent = pages.spend_pages(2)
    with pytest.raises(BudgetExceeded, match=BUDGET_EXHAUSTED):
        spent.spend_pages()
    with pytest.raises(BudgetExceeded):
        spent.spend_search()
    with pytest.raises(BudgetExceeded):
        spent.spend_model_answer()
    with pytest.raises(BudgetExceeded):
        spent.spend_tool_call()
    with pytest.raises(BudgetExceeded):
        spent.spend_handoff()


def test_the_model_answer_cap_is_the_query_limit_times_the_connections():
    budget = SeoBudget.for_connections(3)
    assert budget.max_model_answers == GENERATED_QUERY_LIMIT * 3
    assert budget.spend_model_answer(budget.max_model_answers).model_answers == 120
    with pytest.raises(BudgetExceeded):
        budget.spend_model_answer(budget.max_model_answers + 1)
    with pytest.raises(ToolRejected):
        SeoBudget.for_connections(-1)
    with pytest.raises(ToolRejected):
        SeoBudget.for_connections(True)  # type: ignore[arg-type]


def test_turns_are_counted_per_specialist_and_never_for_the_supervisor():
    budget = SeoBudget.for_connections(1)
    spent = budget.spend_turn("site").spend_turn("site").spend_turn("queries")

    assert budget.turns_for("site") == 0
    assert spent.turns_for("site") == 2
    assert spent.turns_for("queries") == 1
    assert spent.turns_for("checks") == 0

    full = SeoBudget(max_turns=1).spend_turn("report")
    with pytest.raises(BudgetExceeded):
        full.spend_turn("report")
    assert full.spend_turn("site").turns_for("site") == 1
    with pytest.raises(ToolRejected):
        spent.spend_turn("supervisor")


def test_the_budget_summary_reports_used_versus_cap():
    budget = SeoBudget.for_connections(2)
    summary = budget.spend_pages(3).spend_search(1).spend_turn("checks").as_dict()

    assert summary["pages"] == {"used": 3, "cap": MAX_FETCH_PAGES}
    assert summary["searches"] == {"used": 1, "cap": MAX_SEARCH_REQUESTS}
    assert summary["model_answers"] == {"used": 0, "cap": GENERATED_QUERY_LIMIT * 2}
    assert summary["tool_calls"] == {"used": 0, "cap": MAX_TOOL_CALLS}
    assert summary["handoffs"] == {"used": 0, "cap": MAX_SUPERVISOR_HANDOFFS}
    assert summary["turns"] == {"checks": {"used": 1, "cap": MAX_SPECIALIST_TURNS}}
    assert budget.as_dict()["turns"] == {}
