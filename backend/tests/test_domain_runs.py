"""Combined run validation and public summary-table semantics."""

import pytest

from app.core.errors import ValidationError
from app.domain.runs import normalize_run_request, summary_rows


def test_model_only_does_not_require_site():
    run = normalize_run_request({
        "brand": "Ромашка", "domain": "", "prompts_text": "цветы",
        "provider_ids": ["p"], "regions": [],
    })
    assert (run.brand, run.domain, run.prompts, run.provider_ids, run.regions, run.search_host) == (
        "Ромашка", "", ("цветы",), ("p",), (), None,
    )


def test_search_only_does_not_require_brand():
    run = normalize_run_request({
        "brand": "", "domain": "https://Shop.Example.ru/path",
        "prompts_text": "цветы", "provider_ids": [], "regions": [1],
    })
    assert run.brand == ""
    assert run.search_host == "shop.example.ru"
    assert run.regions == (1,)


def test_mixed_run_obeys_the_stricter_yandex_question_limit():
    with pytest.raises(ValidationError):
        normalize_run_request({
            "brand": "Ромашка", "domain": "example.ru",
            "prompts_text": "x" * 401, "provider_ids": ["p"], "regions": [1],
        })


@pytest.mark.parametrize("selection", [
    {"provider_ids": [], "regions": []},
    {"provider_ids": "p", "regions": []},
    {"provider_ids": [], "regions": "1"},
])
def test_invalid_selection_never_starts_a_run(selection):
    with pytest.raises(ValidationError):
        normalize_run_request({
            "brand": "Ромашка", "domain": "example.ru",
            "prompts_text": "цветы", **selection,
        })


def test_summary_rows_keep_duplicate_prompts_and_region_order():
    models = [
        {"provider_id": "p", "provider_name": "ChatGPT", "prompt": "цветы",
         "prompt_index": i, "status": "mentioned" if i else "absent",
         "answer": "Ромашка" if i else "другой бренд",
         "mentioned": bool(i), "error": None}
        for i in range(2)
    ]
    search = [
        {"prompt": "цветы", "prompt_index": prompt_index, "region_id": region_id,
         "region_index": region_index, "region_name": region_name,
         "status": "found" if region_id == 1 else "absent",
         "position": 2 if region_id == 1 else None, "url": None, "error": None}
        for prompt_index in range(2)
        for region_index, (region_id, region_name) in enumerate(((1, "Москва"), (213, "Москва-город")))
    ]
    rows = summary_rows(models, search, provider_ids=("p",), regions=(1, 213))
    assert rows == [
        {"prompt": "цветы", "source": "Яндекс", "language": "ru", "region": "Москва",
         "ai_answer": "—", "site_found": "Да", "position": "2", "brand_found": "—", "status": "Готово"},
        {"prompt": "цветы", "source": "Яндекс", "language": "ru", "region": "Москва",
         "ai_answer": "—", "site_found": "Да", "position": "2", "brand_found": "—", "status": "Готово"},
        {"prompt": "цветы", "source": "Яндекс", "language": "ru", "region": "Москва-город",
         "ai_answer": "—", "site_found": "Нет", "position": "—", "brand_found": "—", "status": "Готово"},
        {"prompt": "цветы", "source": "Яндекс", "language": "ru", "region": "Москва-город",
         "ai_answer": "—", "site_found": "Нет", "position": "—", "brand_found": "—", "status": "Готово"},
        {"prompt": "цветы", "source": "ChatGPT", "language": "", "region": "—",
         "ai_answer": "Да", "site_found": "—", "position": "—", "brand_found": "Нет", "status": "Готово"},
        {"prompt": "цветы", "source": "ChatGPT", "language": "", "region": "—",
         "ai_answer": "Да", "site_found": "—", "position": "—", "brand_found": "Да", "status": "Готово"},
    ]


def test_unknown_results_never_look_like_negative_results():
    rows = summary_rows(
        [{"provider_id": "p", "provider_name": "ChatGPT", "prompt": "цветы",
          "prompt_index": 0, "status": "interrupted", "answer": None,
          "mentioned": None, "error": None}],
        [{"prompt": "цветы", "prompt_index": 0, "region_id": 1, "region_index": 0,
          "region_name": "Москва", "status": "error", "position": None,
          "url": None, "error": "Ошибка API"}],
        provider_ids=("p",), regions=(1,),
    )
    assert rows[0]["site_found"] == "—"
    assert rows[0]["status"] == "Ошибка"
    assert rows[1]["brand_found"] == "—"
    assert rows[1]["status"] == "Прервано"
