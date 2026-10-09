"""Report metrics of the SEO analysis: site, competitors, categories, and services."""

from __future__ import annotations

import pytest

from app.domain.seo import (
    QUERY_CATEGORIES,
    Candidate,
    CandidateHit,
    GeneratedQuery,
    ModelRowValue,
    QueryFlags,
    SearchRowValue,
    SeoInput,
)
from app.domain.seo_answer import Citation, SeoAnswer
from app.domain.seo_report import Metric, build_report


def seo_input(**overrides: object) -> SeoInput:
    base: dict[str, object] = {
        "url": "https://example.ru/",
        "host": "example.ru",
        "sphere": "Стоматология",
        "seeds": ("лечение зубов", "имплантация", "брекеты"),
        "services": ("Лечение", "Имплантация"),
        "connection_ids": ("conn-1",),
    }
    base.update(overrides)
    return SeoInput(**base)  # type: ignore[arg-type]


def query(
    index: int,
    *,
    text: str | None = None,
    category: str = "commercial",
    service: str | None = None,
    branded: bool = False,
    name: bool = False,
    host: bool = False,
    candidate: bool = False,
) -> GeneratedQuery:
    return GeneratedQuery(
        text=text or f"запрос {index}",
        category=category,
        service=service,
        flags=QueryFlags(name, host, candidate, branded),
    )


def search_row(
    index: int,
    status: str = "found",
    position: int | None = 1,
    *,
    url: str | None = None,
    error: str | None = None,
) -> SearchRowValue:
    return SearchRowValue(
        query_index=index,
        status=status,  # type: ignore[arg-type]
        site_position=position if status == "found" else None,
        site_url=url if status == "found" else None,
        error=error,
    )


def model_row(
    connection_id: str,
    index: int,
    status: str = "found",
    answer: str | None = "Ответ модели",
    *,
    name: bool = False,
    host: bool = False,
    error: str | None = None,
    seo_answer: SeoAnswer | None = None,
) -> ModelRowValue:
    return ModelRowValue(
        connection_id=connection_id,
        query_index=index,
        status=status,  # type: ignore[arg-type]
        answer=answer,
        name_mentioned=name,
        host_mentioned=host,
        error=error,
        seo_answer=seo_answer,
    )


def web_answer(*urls: str, search_status: str = "completed") -> SeoAnswer:
    """A saved answer citing the given URLs in order, with the web search finished."""
    return SeoAnswer(
        text="Ответ со ссылками",
        answer_mode="deepseek_web",
        search_status=search_status,  # type: ignore[arg-type]
        search_results=(),
        citations=tuple(
            Citation(url=url, title=None, cited_text=None, block_index=0, order=order)
            for order, url in enumerate(urls, 1)
        ),
        model="Модель",
        search_calls=1,
    )


EMPTY = Metric(0, 0, None, None)


def empty_position() -> dict[str, object]:
    return {"first": EMPTY, "early": EMPTY, "late": EMPTY, "absent": EMPTY, "ahead": EMPTY}


def empty_ai() -> dict[str, object]:
    return {
        "name": EMPTY,
        "host": EMPTY,
        "combined": EMPTY,
        "citation": EMPTY,
        "position": empty_position(),
        "branded": {"name": EMPTY, "host": EMPTY, "combined": EMPTY, "citation": EMPTY},
        "unbranded": {"name": EMPTY, "host": EMPTY, "combined": EMPTY, "citation": EMPTY},
    }


def test_site_search_metrics_count_only_finite_rows():
    data = seo_input()
    queries = (query(0, branded=True), query(1), query(2), query(3))
    rows = (
        search_row(0, "found", 3, url="https://example.ru/a"),
        search_row(1, "absent"),
        search_row(2, "error", error="Сбой Яндекса"),
        search_row(3, "found", 7, url="https://example.ru/b"),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, rows, ())
    site = report["site"]["search"]
    assert site["overall"] == Metric(denominator=3, successes=2, share=0.6667, average_position=5.0)
    assert site["branded"] == Metric(denominator=1, successes=1, share=1.0, average_position=3.0)
    assert site["unbranded"] == Metric(denominator=2, successes=1, share=0.5, average_position=7.0)


def test_interrupted_and_cancelled_rows_leave_the_denominator():
    data = seo_input()
    queries = (query(0), query(1), query(2))
    rows = (
        search_row(0, "found", 2),
        search_row(1, "interrupted"),
        search_row(2, "cancelled"),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, rows, ())
    assert report["site"]["search"]["overall"] == Metric(1, 1, 1.0, 2.0)


def test_empty_denominators_and_never_found_positions_are_none():
    data = seo_input()
    report = build_report(data, "", data.services, (), (), (), ())
    assert report["site"]["search"]["overall"] == Metric(0, 0, None, None)
    assert report["site"]["search"]["branded"] == Metric(0, 0, None, None)
    assert report["site"]["ai"] == {"conn-1": empty_ai()}
    assert report["competitors"] == []

    absent_rows = (search_row(0, "absent"), search_row(1, "absent"))
    queries = (query(0), query(1))
    never_found = build_report(data, "Ромашка", data.services, (), queries, absent_rows, ())
    assert never_found["site"]["search"]["overall"] == Metric(2, 0, 0.0, None)


def test_site_ai_metrics_split_name_host_and_combined_per_connection():
    data = seo_input()
    queries = (query(0, branded=True), query(1), query(2))
    rows = (
        model_row("conn-1", 0, answer="Ромашка рекомендует example.ru", name=True, host=True),
        model_row("conn-1", 1, answer="example.ru лучший", host=True),
        model_row("conn-1", 2, "absent", "Ничего не найдено"),
        model_row("conn-2", 0, "error", None, error="Сбой модели"),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, (), rows)
    ai = report["site"]["ai"]
    assert list(ai) == ["conn-1", "conn-2"]
    assert ai["conn-1"]["name"] == Metric(3, 1, 0.3333, None)
    assert ai["conn-1"]["host"] == Metric(3, 2, 0.6667, None)
    assert ai["conn-1"]["combined"] == Metric(3, 2, 0.6667, None)
    assert ai["conn-1"]["branded"] == {
        "name": Metric(1, 1, 1.0, None),
        "host": Metric(1, 1, 1.0, None),
        "combined": Metric(1, 1, 1.0, None),
        "citation": EMPTY,
    }
    assert ai["conn-1"]["unbranded"]["combined"] == Metric(2, 1, 0.5, None)
    assert ai["conn-2"]["combined"] == Metric(0, 0, None, None)


def test_an_empty_model_answer_is_not_a_success():
    data = seo_input()
    rows = (model_row("conn-1", 0, answer="   ", name=True, host=True),)
    report = build_report(data, "Ромашка", data.services, (), (query(0),), (), rows)
    assert report["site"]["ai"]["conn-1"]["combined"] == Metric(1, 0, 0.0, None)


def test_categories_split_search_and_ai_metrics_for_the_site():
    data = seo_input()
    queries = (
        query(0, category="commercial", service="Имплантация", branded=True),
        query(1, category="commercial", service="Имплантация"),
        query(2, category="informational"),
        query(3, category="comparative", service="Брекеты"),
    )
    rows = (
        search_row(0, "found", 2),
        search_row(1, "absent"),
        search_row(2, "found", 4),
        search_row(3, "error", error="Сбой Яндекса"),
    )
    models = (
        model_row("conn-1", 0, "found", "Ромашка", name=True),
        model_row("conn-1", 1, "absent", "нет"),
        model_row("conn-1", 2, "found", "example.ru", host=True),
        model_row("conn-1", 3, "error", None, error="Сбой"),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, rows, models)
    categories = report["categories"]
    assert set(categories) == set(QUERY_CATEGORIES)
    assert categories["commercial"]["search"] == Metric(2, 1, 0.5, 2.0)
    assert categories["commercial"]["ai"] == {"conn-1": Metric(2, 1, 0.5, None)}
    assert categories["informational"]["search"] == Metric(1, 1, 1.0, 4.0)
    assert categories["informational"]["ai"] == {"conn-1": Metric(1, 1, 1.0, None)}
    assert categories["comparative"]["search"] == Metric(0, 0, None, None)
    assert categories["comparative"]["ai"] == {"conn-1": Metric(0, 0, None, None)}


def test_services_split_metrics_and_use_an_empty_key_for_unbound_queries():
    data = seo_input()
    queries = (
        query(0, service="Имплантация"),
        query(1, service="Имплантация", branded=True),
        query(2),
    )
    rows = (search_row(0, "found", 1), search_row(1, "absent"), search_row(2, "found", 9))
    models = (
        model_row("conn-1", 0, "found", "example.ru", host=True),
        model_row("conn-1", 1, "absent", "нет"),
        model_row("conn-1", 2, "found", "Ромашка", name=True),
    )
    report = build_report(
        data, "Ромашка", ("Имплантация", "Брекеты"), (), queries, rows, models
    )
    services = report["services"]
    assert list(services) == ["Имплантация", "Брекеты", ""]
    assert services["Имплантация"]["search"] == Metric(2, 1, 0.5, 1.0)
    assert services["Имплантация"]["ai"] == {"conn-1": Metric(2, 1, 0.5, None)}
    assert services["Брекеты"]["search"] == Metric(0, 0, None, None)
    assert services[""]["search"] == Metric(1, 1, 1.0, 9.0)
    assert services[""]["ai"] == {"conn-1": Metric(1, 1, 1.0, None)}


def candidates() -> tuple[Candidate, ...]:
    return (
        Candidate(
            host="rival.ru",
            title="Rival",
            occurrences=2,
            average_position=2.0,
            seed_indexes=(0, 1),
            recurring=True,
        ),
        Candidate(
            host="one-off.ru",
            title="One off",
            occurrences=1,
            average_position=5.0,
            seed_indexes=(0,),
            recurring=False,
        ),
    )


def test_competitor_metrics_use_candidate_hits_and_saved_model_answers():
    data = seo_input()
    queries = (query(0, text="rival.ru отзывы", branded=True), query(1), query(2))
    rows = (search_row(0, "found", 1), search_row(1, "found", 3), search_row(2, "absent"))
    hits = {
        0: (CandidateHit(host="rival.ru", position=2, url="https://rival.ru/a"),),
        1: (
            CandidateHit(host="rival.ru", position=3),
            CandidateHit(host="one-off.ru", position=5),
        ),
    }
    models = (
        model_row("conn-1", 0, "found", "Смотрите rival.ru", host=True),
        model_row("conn-1", 1, "found", "rival.ru лучше", host=False),
        model_row("conn-1", 2, "found", "нет упоминаний"),
    )
    report = build_report(
        data,
        "Ромашка",
        data.services,
        candidates(),
        queries,
        rows,
        models,
        candidate_hits=hits,
    )
    competitors = report["competitors"]
    assert [item["host"] for item in competitors] == ["rival.ru"]
    rival = competitors[0]
    assert rival["title"] == "Rival"
    assert rival["occurrences"] == 2
    assert rival["average_position"] == 2.0
    assert rival["seed_indexes"] == (0, 1)
    assert rival["search"]["overall"] == Metric(3, 2, 0.6667, 2.5)
    assert rival["search"]["branded"] == Metric(1, 1, 1.0, 2.0)
    assert rival["search"]["unbranded"] == Metric(2, 1, 0.5, 3.0)
    assert rival["ai"] == {"conn-1": {"host": Metric(3, 2, 0.6667, None), "citation": EMPTY}}


def test_candidate_hits_of_an_error_row_are_not_counted():
    data = seo_input()
    rows = (search_row(0, "error", error="Сбой"),)
    hits = {0: (CandidateHit(host="rival.ru", position=1),)}
    report = build_report(
        data,
        "Ромашка",
        data.services,
        (candidates()[0],),
        (query(0),),
        rows,
        (),
        candidate_hits=hits,
    )
    assert report["competitors"][0]["search"]["overall"] == Metric(0, 0, None, None)
    assert report["competitors"][0]["ai"] == {"conn-1": {"host": Metric(0, 0, None, None), "citation": EMPTY}}


# -- brand position -----------------------------------------------------------


def test_the_brand_position_counts_the_paragraph_of_the_first_mention():
    data = seo_input()
    queries = (query(0), query(1), query(2))
    report = build_report(
        data, "Ромашка", data.services, (), queries,
        (), (model_row("conn-1", 0, answer="Ромашка в первом абзаце.\n\nВторой."),
             model_row("conn-1", 1, answer="Раз.\n\nДва.\n\nТри.\n\nРомашка тут."),
             model_row("conn-1", 2, "absent", answer="Ничего про бренд.")),
    )
    position = report["site"]["ai"]["conn-1"]["position"]
    assert position["first"].successes == 1
    assert position["late"].successes == 1
    assert position["absent"].successes == 1
    assert position["first"].denominator == 3
    assert position["early"].successes == 0
    assert position["absent"].denominator == 3
    assert position["first"] == Metric(3, 1, 0.3333, None)


def test_a_single_paragraph_answer_is_the_first_paragraph():
    data = seo_input()
    report = build_report(data, "Ромашка", data.services, (), (query(0),), (),
                          (model_row("conn-1", 0, answer="Ромашка упомянута сразу."),))
    assert report["site"]["ai"]["conn-1"]["position"]["first"].successes == 1


def test_the_brand_host_counts_as_a_brand_mention():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, (), (query(0),), (),
        (model_row("conn-1", 0, answer="Раз.\n\nСайт example.ru во втором абзаце."),),
    )
    assert report["site"]["ai"]["conn-1"]["position"]["early"] == Metric(1, 1, 1.0, None)


def test_the_second_and_third_paragraphs_count_as_early():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, (), (query(0), query(1)), (),
        (model_row("conn-1", 0, answer="Раз.\n\nРомашка тут.\n\nТри."),
         model_row("conn-1", 1, answer="Раз.\n\nДва.\n\nРомашка на третьем.")),
    )
    position = report["site"]["ai"]["conn-1"]["position"]
    assert position["early"] == Metric(2, 2, 1.0, None)
    assert position["first"].successes == 0
    assert position["late"].successes == 0


def test_position_counts_absent_and_ignores_error_and_empty_answers():
    data = seo_input()
    queries = (query(0), query(1), query(2), query(3))
    report = build_report(
        data, "Ромашка", data.services, (), queries, (),
        (model_row("conn-1", 0, answer="Ромашка в первом абзаце."),
         model_row("conn-1", 1, "found", "   "),
         model_row("conn-1", 2, "error", None, error="Сбой модели"),
         model_row("conn-1", 3, "absent", "Ничего про бренд.")),
    )
    position = report["site"]["ai"]["conn-1"]["position"]
    assert position["first"] == Metric(2, 1, 0.5, None)
    assert position["absent"] == Metric(2, 1, 0.5, None)
    assert position["early"] == Metric(2, 0, 0.0, None)


def test_position_is_not_duplicated_into_the_branded_and_unbranded_splits():
    data = seo_input()
    queries = (query(0, branded=True), query(1))
    report = build_report(
        data, "Ромашка", data.services, (), queries, (),
        (model_row("conn-1", 0, answer="Ромашка в первом абзаце."),
         model_row("conn-1", 1, answer="Раз.\n\nРомашка во втором.")),
    )
    ai = report["site"]["ai"]["conn-1"]
    assert "position" not in ai["branded"]
    assert "position" not in ai["unbranded"]
    assert ai["position"]["first"].denominator == 2


def test_the_brand_is_ahead_when_no_candidate_is_mentioned_earlier():
    # candidate host: rival.ru; the brand in paragraph 1, the candidate in paragraph 2
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, candidates(), (query(0),), (),
        (model_row("conn-1", 0, answer="Ромашка в первом абзаце.\n\nВторой абзац про rival.ru."),),
    )
    ahead = report["site"]["ai"]["conn-1"]["position"]["ahead"]
    assert ahead.denominator == 1
    assert ahead.successes == 1
    assert ahead.share == 1.0


def test_a_candidate_named_earlier_keeps_the_brand_behind():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, candidates(), (query(0),), (),
        (model_row("conn-1", 0, answer="Сначала rival.ru.\n\nПотом Ромашка."),),
    )
    assert report["site"]["ai"]["conn-1"]["position"]["ahead"] == Metric(1, 0, 0.0, None)


def test_a_candidate_in_the_same_paragraph_does_not_put_the_brand_ahead():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, candidates(), (query(0),), (),
        (model_row("conn-1", 0, answer="Ромашка и rival.ru в одном абзаце.\n\nЕщё абзац."),),
    )
    assert report["site"]["ai"]["conn-1"]["position"]["ahead"] == Metric(1, 0, 0.0, None)


def test_a_candidate_without_the_brand_enters_the_ahead_denominator():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, candidates(), (query(0),), (),
        (model_row("conn-1", 0, "absent", "В ответе только rival.ru."),),
    )
    position = report["site"]["ai"]["conn-1"]["position"]
    assert position["ahead"] == Metric(1, 0, 0.0, None)
    assert position["absent"] == Metric(1, 1, 1.0, None)


def test_the_brand_behind_one_of_two_candidates_is_not_ahead():
    data = seo_input()
    report = build_report(
        data, "Ромашка", data.services, candidates(), (query(0),), (),
        (model_row("conn-1", 0, answer="Сначала rival.ru.\n\nПотом Ромашка.\n\nИ one-off.ru."),),
    )
    assert report["site"]["ai"]["conn-1"]["position"]["ahead"] == Metric(1, 0, 0.0, None)


def test_the_ahead_metric_has_an_empty_denominator_without_candidates():
    data = seo_input()
    report = build_report(data, "Ромашка", data.services, (), (query(0),), (),
                          (model_row("conn-1", 0, answer="Ромашка в первом абзаце."),))
    ahead = report["site"]["ai"]["conn-1"]["position"]["ahead"]
    assert ahead.denominator == 0
    assert ahead.successes == 0
    assert ahead.share is None


# -- sources ------------------------------------------------------------------


def test_sources_rank_external_domains_and_skip_the_own_host():
    data = seo_input()
    queries = (query(0), query(1))
    models = (
        model_row("conn-1", 0, seo_answer=web_answer(
            "https://habr.com/first", "https://habr.com/second",
            "https://example.ru/page", "not-a-url", "https://localhost/private",
        )),
        model_row("conn-1", 1, seo_answer=web_answer(
            "https://habr.com/third", "https://blog.example.ru/post",
        )),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, (), models)

    assert report["sources"][0] == {"domain": "habr.com", "answers": 2, "citations": 3}
    assert all(item["domain"] != "example.ru" for item in report["sources"])
    # The own subdomain and the unparseable URLs add nothing either.
    assert report["sources"] == [{"domain": "habr.com", "answers": 2, "citations": 3}]


def test_a_row_without_completed_web_search_never_reaches_sources():
    data = seo_input()
    queries = (query(0), query(1), query(2))
    models = (
        model_row("conn-1", 0, seo_answer=web_answer("https://habr.com/a", search_status="error")),
        model_row("conn-1", 1, seo_answer=web_answer("https://vc.ru/b", search_status="not_requested")),
        model_row("conn-1", 2, answer="Текстовый ответ без веб-поиска"),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, (), models)

    assert report["sources"] == []


def test_sources_are_sorted_by_answers_then_citations_then_domain():
    data = seo_input()
    queries = (query(0), query(1))
    models = (
        model_row("conn-1", 0, seo_answer=web_answer(
            "https://alfa.ru/1", "https://beta.ru/1", "https://gamma.ru/1",
            "https://delta.ru/1", "https://epsilon.ru/1",
        )),
        model_row("conn-1", 1, seo_answer=web_answer(
            "https://alfa.ru/2", "https://gamma.ru/2", "https://gamma.ru/3",
        )),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, (), models)

    assert report["sources"] == [
        {"domain": "gamma.ru", "answers": 2, "citations": 3},
        {"domain": "alfa.ru", "answers": 2, "citations": 2},
        {"domain": "beta.ru", "answers": 1, "citations": 1},
        {"domain": "delta.ru", "answers": 1, "citations": 1},
        {"domain": "epsilon.ru", "answers": 1, "citations": 1},
    ]


def test_sources_keep_only_the_twenty_most_cited_domains():
    data = seo_input()
    urls = tuple(f"https://site{index:02d}.ru/page" for index in range(1, 26))
    models = (model_row("conn-1", 0, seo_answer=web_answer(*urls)),)
    report = build_report(data, "Ромашка", data.services, (), (query(0),), (), models)

    domains = [item["domain"] for item in report["sources"]]
    assert len(domains) == 20
    assert domains == [f"site{index:02d}.ru" for index in range(1, 21)]


def test_counts_report_queries_rows_and_errors():
    data = seo_input()
    queries = (query(0), query(1), query(2))
    rows = (
        search_row(0, "found", 1),
        search_row(1, "error", error="Сбой"),
        search_row(2, "cancelled"),
    )
    models = (
        model_row("conn-1", 0, "found", "Ромашка", name=True),
        model_row("conn-1", 1, "error", None, error="Сбой"),
        model_row("conn-1", 2, "interrupted", None),
    )
    report = build_report(data, "Ромашка", data.services, (), queries, rows, models)
    assert report["counts"] == {
        "queries": 3,
        "search_rows": 3,
        "model_rows": 3,
        "search_errors": 2,
        "model_errors": 2,
    }


def test_the_report_has_the_documented_top_level_keys():
    data = seo_input()
    report = build_report(data, "Ромашка", data.services, (), (), (), ())
    assert set(report) == {"site", "competitors", "categories", "services", "sources", "counts"}


def test_metric_share_is_a_fraction_and_position_is_none_for_ai():
    metric = Metric(denominator=4, successes=1, share=0.25, average_position=None)
    assert metric.share == pytest.approx(0.25)
    assert metric.average_position is None


def computed_report() -> dict[str, object]:
    """A report with every block filled, so a wrapper can be compared key by key."""
    data = seo_input()
    queries = (query(0, branded=True), query(1, service="Имплантация"), query(2, category="informational"))
    rows = (
        search_row(0, "found", 2, url="https://example.ru/a"),
        search_row(1, "absent"),
        search_row(2, "error", error="Сбой Яндекса"),
    )
    models = (
        model_row("conn-1", 0, "found", "Ромашка и example.ru", name=True, host=True),
        model_row("conn-1", 1, "absent", "нет упоминаний"),
        model_row("conn-1", 2, "error", None, error="Сбой модели"),
    )
    return build_report(
        data,
        "Ромашка",
        data.services,
        candidates(),
        queries,
        rows,
        models,
        candidate_hits={0: (CandidateHit(host="rival.ru", position=2, url="https://rival.ru/a"),)},
    )
