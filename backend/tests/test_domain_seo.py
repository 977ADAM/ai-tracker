"""Pure SEO rules: request normalization, services, candidates, and generated queries."""

from __future__ import annotations

import json
from typing import get_args

import pytest

from app.core.errors import ValidationError
from app.domain.seo import (
    AGENT_LABELS,
    AGENTS,
    CATEGORY_LABELS,
    GENERATED_QUERY_LIMIT,
    INVALID_HOST_IP,
    INVALID_SITE,
    MAX_QUERY_LENGTH,
    MAX_QUERY_WORDS,
    MIN_GENERATED_QUERIES,
    QUERY_CATEGORIES,
    AgentStatus,
    Candidate,
    GeneratedQuery,
    QueryFlags,
    SeedResult,
    accept_generated_queries,
    flag_queries,
    hosts_match,
    merge_services,
    normalize_seo_request,
    rank_candidates,
    url_problem,
)


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "url": "https://Example.ru/",
        "sphere": "Стоматология",
        "seeds": ["лечение зубов", "имплантация", "брекеты"],
        "services": ["Лечение", "Имплантация"],
        "connection_ids": ["conn-1"],
    }
    base.update(overrides)
    return base


def generated_query(
    text: str,
    *,
    category: str = "commercial",
    service: str | None = None,
    flags: QueryFlags | None = None,
) -> GeneratedQuery:
    return GeneratedQuery(
        text=text,
        category=category,
        service=service,
        flags=flags or QueryFlags(False, False, False, False),
    )


def item(query: str, category: str = "commercial", service: object = None) -> dict[str, object]:
    return {"query": query, "category": category, "service": service}


def seed(query_index: int, *documents: tuple[int, str, str]) -> SeedResult:
    return SeedResult(query_index=query_index, documents=documents)


def test_normalizes_the_request_and_canonicalizes_the_host():
    result = normalize_seo_request(
        payload(url="https://WWW.Example.RU:8443/main?x=1#top", sphere="  Стоматология  ")
    )
    assert result.url == "https://WWW.Example.RU:8443/main?x=1#top"
    assert result.host == "example.ru"
    assert result.sphere == "Стоматология"
    assert result.seeds == ("лечение зубов", "имплантация", "брекеты")
    assert result.services == ("Лечение", "Имплантация")
    assert result.connection_ids == ("conn-1",)


def test_key_queries_keep_the_entered_spelling():
    result = normalize_seo_request(payload(seeds=["  Лечение Зубов  ", "имплантация", "Брекеты"]))
    assert result.seeds == ("Лечение Зубов", "имплантация", "Брекеты")


def test_the_seo_limits_and_labels_are_the_agreed_ones():
    assert GENERATED_QUERY_LIMIT == 7
    assert MIN_GENERATED_QUERIES == 2
    assert QUERY_CATEGORIES == ("commercial", "informational", "comparative", "recommendation")
    assert CATEGORY_LABELS == {
        "commercial": "Коммерческие",
        "informational": "Информационные",
        "comparative": "Сравнительные",
        "recommendation": "Рекомендовательные",
    }
    assert MAX_QUERY_LENGTH == 400
    assert MAX_QUERY_WORDS == 40


def test_the_four_query_categories_and_their_russian_labels_are_fixed():
    assert QUERY_CATEGORIES == ("commercial", "informational", "comparative", "recommendation")
    assert CATEGORY_LABELS["recommendation"] == "Рекомендовательные"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "не объект",
        [],
        payload(extra="поле"),
        payload(url=""),
        payload(url="   "),
        payload(url="localhost"),
        payload(url="ftp://example.ru"),
        payload(url="https://user:secret@example.ru"),
        payload(sphere=""),
        payload(sphere="   "),
        payload(sphere="с" * 201),
        payload(sphere=42),
        payload(seeds=[]),
        payload(seeds=["раз", "два"]),
        payload(seeds=["раз", "два", "три", "четыре"]),
        payload(seeds=["раз", "два", "раз"]),
        payload(seeds=["раз", "два", "РАЗ"]),
        payload(seeds=["раз", "два", "   "]),
        payload(seeds=["раз", "два", 42]),
        payload(seeds=["раз", "два", "x" * 401]),
        payload(seeds=["раз", "два", " ".join(["слово"] * 41)]),
        payload(services=[]),
        payload(services=["услуга"] * 21),
        payload(services=[""]),
        payload(services=[42]),
        payload(services=["услуга", "УСЛУГА"]),
        payload(services=["x" * 101]),
        payload(connection_ids=[]),
        payload(connection_ids=["a"] * 6),
        payload(connection_ids=["a", "a"]),
        payload(connection_ids=[""]),
        payload(connection_ids=[42]),
    ],
)
def test_rejects_an_unusable_request(value):
    with pytest.raises(ValidationError):
        normalize_seo_request(value)


def test_accepts_the_full_request_size():
    result = normalize_seo_request(
        payload(
            sphere="с" * 200,
            seeds=["x" * MAX_QUERY_LENGTH, " ".join(["слово"] * MAX_QUERY_WORDS), "третий"],
            services=[f"услуга {index}" for index in range(20)],
            connection_ids=[f"conn-{index}" for index in range(5)],
        )
    )
    assert len(result.sphere) == 200
    assert len(result.seeds[0]) == MAX_QUERY_LENGTH
    assert len(result.seeds[1].split()) == MAX_QUERY_WORDS
    assert len(result.services) == 20
    assert result.connection_ids == tuple(f"conn-{index}" for index in range(5))


@pytest.mark.parametrize(
    "url",
    [
        "127.0.0.1",
        "http://127.0.0.1:8000/",
        "https://93.184.216.34/",
        "10.0.0.1",
        "192.168.1.10",
        "127.1",
    ],
)
def test_rejects_an_ip_literal_as_the_site(url):
    with pytest.raises(ValidationError, match="IP"):
        normalize_seo_request(payload(url=url))


def test_url_problem_rejects_a_bare_host():
    assert url_problem("example.ru") == INVALID_SITE


def test_url_problem_rejects_an_ip_literal():
    assert url_problem("http://93.184.216.34") == INVALID_HOST_IP


def test_url_problem_accepts_a_public_url():
    assert url_problem(" https://example.ru ") is None


def test_hosts_match_uses_the_task_two_host_rules():
    assert hosts_match("example.ru", "example.ru") is True
    assert hosts_match("example.ru", "WWW.Example.RU.") is True
    assert hosts_match("example.ru", "shop.example.ru") is True
    assert hosts_match("example.ru", "https://shop.example.ru/catalog") is True
    assert hosts_match("example.ru", "example.ru.attacker.test") is False
    assert hosts_match("example.ru", "notexample.ru") is False
    assert hosts_match("", "example.ru") is False
    assert hosts_match("example.ru", "") is False


def test_merge_services_keeps_user_order_and_spelling():
    merged = merge_services(("Лечение зубов", "Имплантация"), ("имплантация", "Брекеты", ""))
    assert merged == ("Лечение зубов", "Имплантация", "Брекеты")


def test_merge_services_handles_empty_inputs():
    assert merge_services((), ()) == ()
    assert merge_services((), ("Услуга",)) == ("Услуга",)
    assert merge_services(("Услуга",), ()) == ("Услуга",)


def test_rank_candidates_counts_occurrences_and_average_position():
    results = (
        seed(
            0,
            (1, "https://other.ru/", "Other"),
            (2, "https://example.ru/", "Example"),
            (3, "https://rival.ru/a", "Rival"),
        ),
        seed(1, (1, "https://rival.ru/b", "Rival — главная"), (5, "https://new.ru/", "New")),
        seed(2, (2, "https://rival.ru/c", "Rival")),
    )
    ranked = rank_candidates(results, "example.ru")
    assert [candidate.host for candidate in ranked] == ["rival.ru", "other.ru", "new.ru"]
    rival = ranked[0]
    assert rival.occurrences == 3
    assert rival.average_position == pytest.approx(2.0)
    assert rival.seed_indexes == (0, 1, 2)
    assert rival.recurring is True
    assert rival.title == "Rival"
    assert ranked[1] == Candidate(
        host="other.ru",
        title="Other",
        occurrences=1,
        average_position=1.0,
        seed_indexes=(0,),
        recurring=False,
    )


def test_rank_candidates_excludes_the_user_host_its_subdomains_and_unusable_urls():
    results = (
        seed(
            0,
            (1, "https://example.ru/", ""),
            (2, "https://shop.example.ru/", ""),
            (3, "mailto:hello@example.ru", ""),
            (4, "https://example.ru.attacker.test/", ""),
        ),
        seed(1, (1, "https://other.ru/", "")),
    )
    ranked = rank_candidates(results, "example.ru")
    assert [candidate.host for candidate in ranked] == ["other.ru", "example.ru.attacker.test"]


def test_rank_candidates_needs_two_successful_serps_for_recurring():
    only = (seed(0, (1, "https://rival.ru/", "")),)
    ranked = rank_candidates(only, "example.ru")
    assert ranked[0].recurring is False
    assert rank_candidates((), "example.ru") == ()


def test_rank_candidates_ignores_documents_outside_the_top_ten():
    results = (
        seed(0, (11, "https://rival.ru/", "")),
        seed(1, (10, "https://rival.ru/", "Rival")),
    )
    ranked = rank_candidates(results, "example.ru")
    assert ranked[0].occurrences == 1
    assert ranked[0].average_position == 10.0


def test_rank_candidates_takes_the_first_non_empty_title():
    results = (
        seed(0, (4, "https://rival.ru/", "")),
        seed(1, (2, "https://rival.ru/", "Rival")),
    )
    ranked = rank_candidates(results, "example.ru")
    assert ranked[0].title == "Rival"
    assert ranked[0].average_position == 3.0


def test_accepts_a_valid_generated_payload():
    accepted = accept_generated_queries(
        {
            "queries": [
                item("купить имплантацию", service="Имплантация"),
                item("как лечить зубы", "informational"),
                item("имплантация или протез", "comparative", "протез"),
            ]
        },
        ("Лечение", "Имплантация", "Брекеты"),
    )
    assert [query.text for query in accepted] == [
        "купить имплантацию",
        "как лечить зубы",
        "имплантация или протез",
    ]
    assert accepted[0].category == "commercial"
    assert accepted[0].service == "Имплантация"
    assert accepted[1].category == "informational"
    assert accepted[1].service is None
    assert accepted[2].category == "comparative"
    assert accepted[2].service is None
    assert accepted[0].flags == QueryFlags(False, False, False, False)


def test_accepts_fenced_json_text_and_maps_service_case():
    text = "```json\n" + json.dumps({"queries": [
        item(f"запрос {index}", service="имплантация") for index in range(GENERATED_QUERY_LIMIT)
    ]}) + "\n```"
    accepted = accept_generated_queries(text, ("Имплантация",))
    assert len(accepted) == GENERATED_QUERY_LIMIT
    assert accepted[0].service == "Имплантация"


def test_generated_queries_are_deduplicated_in_model_order_and_truncated_to_the_limit():
    # One duplicate plus one query over the limit: eight entries, seven accepted.
    items = [item("запрос 0")] + [
        item("ЗАПРОС 0" if index == 0 else f"запрос {index}") for index in range(GENERATED_QUERY_LIMIT + 1)
    ]
    accepted = accept_generated_queries({"queries": items}, ())
    assert len(accepted) == GENERATED_QUERY_LIMIT
    assert [query.text for query in accepted] == [f"запрос {index}" for index in range(GENERATED_QUERY_LIMIT)]


def test_rejects_fewer_unique_generated_queries_than_the_minimum():
    items = [item(f"запрос {index}") for index in range(MIN_GENERATED_QUERIES - 1)]
    with pytest.raises(ValidationError, match=f"меньше {MIN_GENERATED_QUERIES}"):
        accept_generated_queries({"queries": items}, ())

    duplicated = [item("один"), item("ОДИН")]
    with pytest.raises(ValidationError, match=f"меньше {MIN_GENERATED_QUERIES}"):
        accept_generated_queries({"queries": duplicated}, ())


@pytest.mark.parametrize("category", ["brand", "", None, 42, "Commercial"])
def test_rejects_an_unknown_generated_category(category):
    items = [item(f"запрос {index}", category) for index in range(5)]
    with pytest.raises(ValidationError):
        accept_generated_queries({"queries": items}, ())


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        "не json",
        {"queries": "строка"},
        {"queries": [{"category": "commercial"}] * 5},
        {"queries": [item(42)] * 5},
        {"queries": [item("запрос", service=42)] * 5},
    ],
)
def test_rejects_a_broken_generated_payload(value):
    with pytest.raises(ValidationError):
        accept_generated_queries(value, ())


def test_rejects_generated_queries_outside_the_yandex_limits():
    too_long = [item("x" * (MAX_QUERY_LENGTH + 1))] + [item(f"запрос {index}") for index in range(4)]
    with pytest.raises(ValidationError):
        accept_generated_queries({"queries": too_long}, ())

    too_wordy = [item(" ".join(["слово"] * (MAX_QUERY_WORDS + 1)))] + [
        item(f"запрос {index}") for index in range(4)
    ]
    with pytest.raises(ValidationError):
        accept_generated_queries({"queries": too_wordy}, ())


def test_accepts_generated_queries_at_the_yandex_limits():
    items = [item("x" * MAX_QUERY_LENGTH), item(" ".join(["слово"] * MAX_QUERY_WORDS))]
    assert len(accept_generated_queries({"queries": items}, ())) == MIN_GENERATED_QUERIES


def test_flag_queries_marks_the_company_name():
    flagged = flag_queries(
        (
            generated_query("«Ромашка» — лучшая клиника"),
            generated_query("Суперромашка рядом"),
            generated_query("Ёлка и стоматология"),
            generated_query("мой бренд"),
            generated_query("просто запрос"),
        ),
        "Ромашка",
        "example.ru",
        (),
    )
    assert flagged[0].flags.mentions_company_name is True
    assert flagged[0].flags.branded is True
    assert flagged[1].flags.mentions_company_name is False
    assert flagged[2].flags.mentions_company_name is False
    assert flagged[4].flags == QueryFlags(False, False, False, False)

    elka = flag_queries((generated_query("Ёлка"),), "елка", "", ())
    assert elka[0].flags.mentions_company_name is True


def test_flag_queries_marks_the_company_host_and_candidate_hosts():
    flagged = flag_queries(
        (
            generated_query("https://www.example.ru/цены"),
            generated_query("notexample.ru цены"),
            generated_query("rival.ru или мы"),
            generated_query("shop.rival.ru лучше"),
            generated_query("example.ru"),
        ),
        "",
        "example.ru",
        ("rival.ru",),
    )
    assert flagged[0].flags.mentions_company_host is True
    assert flagged[0].flags.branded is True
    assert flagged[0].flags.mentions_candidate_host is False
    assert flagged[1].flags.mentions_company_host is False
    assert flagged[1].flags.branded is False
    assert flagged[2].flags.mentions_candidate_host is True
    assert flagged[2].flags.branded is False
    assert flagged[3].flags.mentions_candidate_host is True
    assert flagged[4].flags.mentions_company_host is True
    assert flagged[4].flags.branded is True


def test_the_five_agents_and_their_russian_labels_are_fixed():
    assert AGENTS == ("supervisor", "site", "competitors", "queries", "checks")
    assert set(AGENT_LABELS) == set(AGENTS)
    assert AGENT_LABELS == {
        "supervisor": "Супервизор",
        "site": "Агент сайта",
        "competitors": "Агент конкурентов",
        "queries": "Агент запросов",
        "checks": "Агент проверок",
    }


def test_the_agent_status_vocabulary_is_the_agreed_six():
    assert get_args(AgentStatus) == ("pending", "running", "waiting", "done", "error", "skipped")


def test_the_agent_names_and_status_have_one_source_in_the_domain():
    # The database and the tool layer must reuse the domain tuple and literal
    # instead of repeating them: `is` fails as soon as either redefines its own.
    from app.db import seo as db_seo
    from app.domain import seo_tools

    assert db_seo.AGENTS is AGENTS
    assert seo_tools.AGENTS is AGENTS
    assert get_args(db_seo.AgentStatus) == get_args(AgentStatus)
    assert db_seo.AGENT_STATUSES == frozenset(get_args(AgentStatus))
