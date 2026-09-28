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
from app.domain.seo_report import Metric, build_report, report_payload


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
) -> ModelRowValue:
    return ModelRowValue(
        connection_id=connection_id,
        query_index=index,
        status=status,  # type: ignore[arg-type]
        answer=answer,
        name_mentioned=name,
        host_mentioned=host,
        error=error,
    )


EMPTY = Metric(0, 0, None, None)


def empty_ai() -> dict[str, object]:
    return {
        "name": EMPTY,
        "host": EMPTY,
        "combined": EMPTY,
        "branded": {"name": EMPTY, "host": EMPTY, "combined": EMPTY},
        "unbranded": {"name": EMPTY, "host": EMPTY, "combined": EMPTY},
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
    assert rival["ai"] == {"conn-1": {"host": Metric(3, 2, 0.6667, None)}}


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
    assert report["competitors"][0]["ai"] == {"conn-1": {"host": Metric(0, 0, None, None)}}


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
    assert set(report) == {"site", "competitors", "categories", "services", "counts"}


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


def metrics_only(payload: dict[str, object]) -> dict[str, object]:
    """Return the payload without its conclusions block."""
    return {key: value for key, value in payload.items() if key != "conclusions"}


def test_report_payload_keeps_every_metric_and_adds_the_conclusions_block():
    report = computed_report()
    conclusions = {"summary": "Сводка", "recommendations": "Выводы", "model": "model-1"}
    payload = report_payload(report, conclusions=conclusions)
    assert payload["conclusions"] == conclusions
    assert metrics_only(payload) == report
    assert set(payload) == set(report) | {"conclusions"}
    # The computed report itself is never mutated, and the block is copied.
    assert "conclusions" not in report
    assert payload["conclusions"] is not conclusions


def test_report_payload_without_conclusions_keeps_every_metric():
    report = computed_report()
    payload = report_payload(report)
    assert payload["conclusions"] is None
    assert metrics_only(payload) == report
    assert set(payload) == set(report) | {"conclusions"}


@pytest.mark.parametrize(
    "conclusions",
    [None, {}, {"summary": ""}, "мусор", 42, [], {"summary": 42, "model": None}, {"unknown": {"a": 1}}],
)
def test_a_missing_empty_or_nonsense_conclusions_block_never_changes_a_metric(conclusions):
    report = computed_report()
    payload = report_payload(report, conclusions=conclusions)  # type: ignore[arg-type]
    assert metrics_only(payload) == report


@pytest.mark.parametrize("conclusions", [None, {}, "мусор", 42, [], ()])
def test_an_unusable_conclusions_block_is_reported_as_absent(conclusions):
    payload = report_payload(computed_report(), conclusions=conclusions)  # type: ignore[arg-type]
    assert payload["conclusions"] is None
