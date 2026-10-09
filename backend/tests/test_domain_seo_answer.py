"""Sources must be safe URLs; citations must preserve their evidence order."""

import pytest

from app.domain.seo_answer import (
    Citation,
    SearchResult,
    normalize_source_url,
    normalize_sources,
)


@pytest.mark.parametrize("url", [
    None, 42, "", "javascript:alert(1)", "data:text/html,x", "https://a:b@example.com/",
    "http://localhost/", "https://foo.local/", "http://192.168.1.1/", "http://127.0.0.1/",
    "http://[::1]/", "https://example.invalid/", "https://bad_host.com/",
    "https://example.com:bad/", "https://example.com/ bad", "https://example.com\\@evil.com/",
])
def test_unsafe_sources_are_excluded(url):
    assert normalize_source_url(url) is None


def test_fragment_is_removed_but_query_is_preserved():
    assert normalize_source_url("https://EXAMPLE.com/page?q=1#section") == "https://example.com/page?q=1"


def test_results_are_deduplicated_but_citation_occurrences_remain():
    results, citations = normalize_sources(
        [SearchResult("https://example.com/a#one", "Page"), SearchResult("https://example.com/a#two", "Other")],
        [Citation("https://example.com/a#one", None, "First", 0, 1),
         Citation("https://example.com/a#two", None, "Second", 1, 2),
         Citation("javascript:alert(1)", None, None, 1, 3)],
    )
    assert results == (SearchResult("https://example.com/a", "Page"),)
    assert [c.url for c in citations] == ["https://example.com/a", "https://example.com/a"]
    assert [c.cited_text for c in citations] == ["First", "Second"]
    assert [c.block_index for c in citations] == [0, 1]

