"""Citation shares use search evidence, not links or brand mentions in prose."""

from app.domain.seo import ModelRowValue
from app.domain.seo_answer import Citation, SeoAnswer
from app.domain.seo_report import Metric, build_report
from tests.test_domain_seo_report import query, seo_input


def row(index, urls=(), *, status="found", mode="deepseek_web"):
    evidence = SeoAnswer("Ответ", mode, "completed" if mode == "deepseek_web" else "not_requested", (),
                         tuple(Citation(url, None, None, 0, n) for n, url in enumerate(urls, 1)), "model", 1)
    return ModelRowValue("conn-1", index, status, "Ромашка", True, False, seo_answer=evidence)


def test_citation_denominator_excludes_text_and_errors():
    report = build_report(seo_input(), "Ромашка", (), (), tuple(query(i) for i in range(5)), (), (
        row(0, ["https://example.ru/a"]), row(1, ["https://shop.example.ru/b"]), row(2),
        row(3, ["https://example.ru/"], status="error"), row(4, mode="text"),
    ))
    assert report["site"]["ai"]["conn-1"]["citation"] == Metric(3, 2, 0.6667, 1.0)


def test_citation_position_counts_unique_domains():
    report = build_report(seo_input(), "", (), (), (query(0),), (), (
        row(0, ["https://other.ru/a", "https://other.ru/b", "https://example.ru/"]),
    ))
    assert report["site"]["ai"]["conn-1"]["citation"].average_position == 2.0


def test_empty_search_is_zero_but_no_search_is_unavailable():
    for model_row, expected in [(row(0), Metric(1, 0, 0.0, None)), (row(0, mode="text"), Metric(0, 0, None, None))]:
        report = build_report(seo_input(), "", (), (), (query(0, service="Услуга", branded=True),), (), (model_row,))
        assert report["site"]["ai"]["conn-1"]["citation"] == expected
        assert report["site"]["ai"]["conn-1"]["branded"]["citation"] == expected
        assert report["categories"]["commercial"]["citation"]["conn-1"] == expected
        assert report["services"]["Услуга"]["citation"]["conn-1"] == expected
