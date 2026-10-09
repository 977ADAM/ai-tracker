"""Small checks for the additional setup controls from the references."""

import base64
import io
import zipfile

import pytest

from app.core.errors import ValidationError
from app.domain.measurement_report import build_measurement_report
from app.domain.projects import mentions_project_domain, normalize_project
from app.domain.prompt_import import parse_prompt_file
from tests.test_projects_measurements import project, snapshot


def test_domain_input_scope_groups_and_brand_only_competitor():
    p = normalize_project(
        project(
            site_url="example.ru",
            include_subdomains=False,
            competitors=[{"brand": "Другой бренд", "site_url": ""}],
            queries=[{"text": "Пицца?", "group": "Доставка"}],
        )
    )
    assert p["site_url"] == "https://example.ru"
    assert p["queries"][0]["group"] == "Доставка"
    assert mentions_project_domain("https://example.ru/menu", p)
    assert not mentions_project_domain("https://shop.example.ru/menu", p)
    assert mentions_project_domain(
        "https://shop.example.ru/menu", {**p, "include_subdomains": True}
    )
    assert (
        build_measurement_report(snapshot(p), [], [])["competitors"][0]["brand"]
        == "Другой бренд"
    )


def test_import_txt_and_csv_preserves_groups_and_rejects_invalid_rows():
    assert (
        parse_prompt_file("prompts.txt", "Где пицца?\nГде доставка?".encode())[1][
            "text"
        ]
        == "Где доставка?"
    )
    rows = parse_prompt_file(
        "prompts.csv",
        'Промпт;Группа\n"Пицца, рядом?";Пицца\nГде доставка?;Доставка'.encode(
            "utf-8-sig"
        ),
    )
    assert rows[0] == {"text": "Пицца, рядом?", "category": None, "group": "Пицца"}
    with pytest.raises(ValidationError):
        parse_prompt_file("prompts.csv", "Промпт\nОдинаковый\nОдинаковый".encode())


def test_xlsx_import_reads_inline_strings_and_blocks_formulas():
    def workbook(formula=False):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr(
                "xl/worksheets/sheet1.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Промпт</t></is></c><c r="B1" t="inlineStr"><is><t>Группа</t></is></c></row><row r="2"><c r="A2" t="inlineStr">'
                + ("<f>HYPERLINK()</f>" if formula else "")
                + '<is><t>Где пицца?</t></is></c><c r="B2" t="inlineStr"><is><t>Доставка</t></is></c></row></sheetData></worksheet>',
            )
        return data.getvalue()

    assert parse_prompt_file("prompts.xlsx", workbook())[0]["group"] == "Доставка"
    with pytest.raises(ValidationError):
        parse_prompt_file("prompts.xlsx", workbook(True))


def test_file_import_api_returns_rows_without_creating_project(client):
    response = client.post(
        "/api/projects/import-prompts",
        json={
            "filename": "p.txt",
            "content": base64.b64encode("Пицца?".encode()).decode(),
        },
    )
    assert response.status_code == 200
    assert response.json()["queries"][0]["text"] == "Пицца?"
    assert client.get("/api/projects").json()["items"] == []


def test_subdomain_switch_applies_to_citations_and_yandex():
    p = normalize_project(project(include_subdomains=False, yandex_enabled=True))
    s = snapshot(p)
    row = {
        "query_index": 0,
        "connection_id": "m1",
        "status": "success",
        "answer": "https://shop.example.ru",
        "brand_mentioned": False,
        "domain_mentioned": False,
        "sentiment_status": "not_applicable",
        "sentiment": None,
        "evidence": {
            "text": "https://shop.example.ru",
            "answer_mode": "deepseek_web",
            "search_status": "completed",
            "search_results": [],
            "citations": [
                {
                    "url": "https://shop.example.ru",
                    "title": None,
                    "cited_text": None,
                    "block_index": 0,
                    "order": 1,
                }
            ],
            "model": "test",
            "search_calls": 1,
        },
    }
    searches = [
        {
            "query_index": 0,
            "status": "success",
            "documents": [{"url": "https://shop.example.ru", "title": ""}],
        }
    ]
    report = build_measurement_report(s, [row], searches)
    assert report["models"][0]["citation"]["share"] == 0
    assert report["search"][0]["found"] == 0
    assert report["sources"][0]["domain"] == "shop.example.ru"


def test_comparison_links_measurements_with_the_same_comparison_key(database_dsn):
    from app.db.measurements import MeasurementRepository
    from app.db.projects import ProjectRepository
    from app.domain.seo_answer import SeoAnswer

    projects = ProjectRepository(database_dsn)
    runs = MeasurementRepository(database_dsn)
    p = projects.create(normalize_project(project()))
    first = runs.create(p["id"], snapshot(), {})
    runs.save_answer(
        first,
        (0, "m1"),
        SeoAnswer("Додопицца", "text", "not_requested", (), (), "test", None),
    )
    runs.finish(first, "completed")
    second = runs.create(p["id"], snapshot(), {})
    runs.save_answer(
        second,
        (0, "m1"),
        SeoAnswer("Додопицца", "text", "not_requested", (), (), "test", None),
    )
    runs.finish(second, "completed")
    assert runs.get(second)["comparison"]["visibility_delta"] == 0
    assert runs.get(second)["comparison"]["previous_id"] == first
