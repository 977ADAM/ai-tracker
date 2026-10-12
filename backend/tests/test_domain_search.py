"""Pure Yandex search rules: the region catalog and host matching."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.search import (
    REGIONS,
    TOP_RESULTS,
    SearchDocument,
    first_matching_result,
    normalize_search_host,
)


def test_normalizes_a_national_domain():
    assert normalize_search_host("Пример.РФ") == "xn--e1afmkfd.xn--p1ai"


def test_limits_are_the_agreed_ones():
    assert TOP_RESULTS == 10


def test_region_catalog_holds_distinct_documented_regions():
    ids = [region_id for region_id, _ in REGIONS]
    assert len(ids) == len(set(ids))
    names = dict(REGIONS)
    assert names[1] == "Москва и Московская область"
    assert names[213] == "Москва"
    assert all(isinstance(region_id, int) and region_id > 0 and name for region_id, name in REGIONS)


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
        normalize_search_host(domain)


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
