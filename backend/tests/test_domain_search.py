"""Pure Yandex search rules: request limits, the region catalog, and host matching."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.search import (
    MAX_REGIONS,
    MAX_SEARCH_PROMPT_LENGTH,
    REGIONS,
    TOP_RESULTS,
    SearchDocument,
    first_matching_result,
    normalize_search_host,
    normalize_search_request,
)


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"domain": "example.ru", "prompts_text": "цветы", "regions": [1]}
    base.update(overrides)
    return base


def test_normalizes_a_hostname_prompts_and_regions():
    result = normalize_search_request(
        payload(domain="  Example.RU  ", prompts_text="первый\n\n  второй  \n", regions=[1, 213])
    )
    assert result.domain == "Example.RU"
    assert result.host == "example.ru"
    assert result.prompts == ("первый", "второй")
    assert result.regions == (1, 213)
    assert result.engines == ("yandex", "yandex")


def test_normalizes_region_targets_in_region_order():
    result = normalize_search_request(payload(
        regions=[1, 213], region_targets=[{"region": 213, "engine": "yandex"}, {"region": 1, "engine": "yandex"}]
    ))
    assert result.engines == ("yandex", "yandex")


@pytest.mark.parametrize("targets", [
    [{"region": 1, "engine": "google"}],
    [{"region": 213, "engine": "yandex"}],
    [{"region": 1, "engine": "yandex"}, {"region": 1, "engine": "yandex"}],
    [{"region": True, "engine": "yandex"}],
    "yandex",
])
def test_rejects_invalid_region_targets(targets):
    with pytest.raises(ValidationError):
        normalize_search_request(payload(region_targets=targets))


def test_a_url_keeps_its_host_and_ignores_scheme_path_and_port():
    result = normalize_search_request(payload(domain="https://Example.ru:8443/catalog?page=2#top"))
    assert result.domain == "https://Example.ru:8443/catalog?page=2#top"
    assert result.host == "example.ru"


def test_normalizes_a_national_domain():
    assert normalize_search_host("Пример.РФ") == "xn--e1afmkfd.xn--p1ai"


def test_accepts_the_full_request_size():
    questions = "\n".join(f"вопрос {index}" for index in range(20))
    result = normalize_search_request(payload(prompts_text=questions, regions=[1, 213, 2, 54, 65]))
    assert len(result.prompts) == 20
    assert result.regions == (1, 213, 2, 54, 65)


def test_limits_are_the_agreed_ones():
    assert MAX_SEARCH_PROMPT_LENGTH == 400
    assert MAX_REGIONS == 5
    assert TOP_RESULTS == 10


def test_region_catalog_holds_distinct_documented_regions():
    ids = [region_id for region_id, _ in REGIONS]
    assert len(ids) == len(set(ids))
    names = dict(REGIONS)
    assert names[1] == "Москва и Московская область"
    assert names[213] == "Москва"
    assert all(isinstance(region_id, int) and region_id > 0 and name for region_id, name in REGIONS)


@pytest.mark.parametrize(
    "value",
    [
        {"domain": "example.ru", "prompts_text": "цветы", "regions": []},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": [1, 1]},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": [1, 213, 2, 54, 65, 43]},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": [999_999]},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": ["1"]},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": [True]},
        {"domain": "example.ru", "prompts_text": "цветы", "regions": 1},
        {"domain": "example.ru", "prompts_text": "цветы"},
    ],
)
def test_rejects_invalid_regions(value):
    with pytest.raises(ValidationError):
        normalize_search_request(value)


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "   ",
        "https://",
        "ftp://example.ru",
        "file://example.ru/x",
        "https://user:secret@example.ru",
        "https://exa mple.ru",
        "https://example",
        "https://.ru",
        "https://-example.ru",
        "https://example-.ru",
        "https://exam_ple.ru",
        "https://example.ru\\path",
        "example.ru:99999",
        "x" * 254,
    ],
)
def test_rejects_an_unusable_site(domain):
    with pytest.raises(ValidationError):
        normalize_search_request(payload(domain=domain))


@pytest.mark.parametrize(
    "value",
    [
        {"domain": "example.ru", "prompts_text": "", "regions": [1]},
        {"domain": "example.ru", "prompts_text": "   \n  ", "regions": [1]},
        {"domain": "example.ru", "prompts": [], "regions": [1]},
        {"domain": "example.ru", "prompts": ["вопрос"] * 21, "regions": [1]},
        {"domain": "example.ru", "prompts_text": 42, "regions": [1]},
        {"domain": "example.ru", "prompts_text": "вопрос\n" * 21, "regions": [1]},
        "не объект",
        None,
    ],
)
def test_rejects_an_invalid_question_list(value):
    with pytest.raises(ValidationError):
        normalize_search_request(value)


def test_search_rejects_a_401_character_question():
    with pytest.raises(ValidationError):
        normalize_search_request({"domain": "example.ru", "prompts_text": "x" * 401, "regions": [1]})


def test_search_accepts_a_400_character_question():
    result = normalize_search_request({"domain": "example.ru", "prompts_text": "x" * 400, "regions": [1]})
    assert result.prompts == ("x" * 400,)


def test_search_rejects_more_than_forty_words():
    with pytest.raises(ValidationError, match="40"):
        normalize_search_request(payload(prompts_text=" ".join(["слово"] * 41)))

    result = normalize_search_request(payload(prompts_text=" ".join(["слово"] * 40)))
    assert len(result.prompts[0].split()) == 40


def test_subdomains_match_but_lookalikes_do_not():
    docs = (
        SearchDocument("https://example.ru.attacker.test/x"),
        SearchDocument("https://shop.example.ru/p"),
    )
    assert first_matching_result("example.ru", docs) == (2, "https://shop.example.ru/p")


def test_exact_host_matches_at_its_own_position():
    docs = (SearchDocument("https://other.ru/"), SearchDocument("http://WWW.Example.RU/catalog"))
    assert first_matching_result("example.ru", docs) == (2, "http://WWW.Example.RU/catalog")


def test_only_the_first_ten_results_are_considered():
    nine = tuple(SearchDocument(f"https://site{index}.ru/") for index in range(9))
    match = SearchDocument("https://example.ru/")
    beyond = SearchDocument("https://shop.example.ru/")
    assert first_matching_result("example.ru", nine + (match,)) == (10, "https://example.ru/")
    assert first_matching_result("example.ru", nine + (match, beyond)) == (10, "https://example.ru/")
    assert first_matching_result("example.ru", nine + (SearchDocument("https://x.ru/"), beyond)) is None


@pytest.mark.parametrize(
    "url",
    [
        "mailto:hello@example.ru",
        "ftp://example.ru/file",
        "javascript:alert(1)",
        "example.ru",
        "https://",
        "https:///catalog",
        "not a url",
    ],
)
def test_a_result_that_is_not_an_http_url_never_matches(url):
    assert first_matching_result("example.ru", (SearchDocument(url),)) is None
