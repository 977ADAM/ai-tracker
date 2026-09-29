"""Pure rules of the SSRF-safe public site fetcher: hosts, addresses, and limits."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.domain.site_fetch import (
    FETCH_CONNECT_TIMEOUT,
    FETCH_TOTAL_TIMEOUT,
    MAX_FETCH_BYTES,
    MAX_FETCH_PAGES,
    MAX_FETCH_REDIRECTS,
    MAX_PAGE_TEXT_CHARS,
    FetchedPage,
    canonical_host,
    is_public_address,
    same_site_host,
)


def test_canonical_host_keeps_only_the_host_of_a_url():
    assert canonical_host("https://Example.RU/catalog?page=2#top") == "example.ru"
    assert canonical_host("http://example.ru") == "example.ru"
    assert canonical_host("example.ru") == "example.ru"
    assert canonical_host("example.ru:8443") == "example.ru"
    assert canonical_host("https://example.ru:8443") == "example.ru"


def test_canonical_host_drops_a_trailing_dot_and_a_leading_www():
    assert canonical_host("  Example.ru.  ") == "example.ru"
    assert canonical_host("www.example.ru") == "example.ru"
    assert canonical_host("WWW.Example.RU.") == "example.ru"
    assert canonical_host("https://www.example.ru/shop") == "example.ru"
    assert canonical_host("https://shop.example.ru") == "shop.example.ru"


def test_canonical_host_normalizes_a_national_domain():
    assert canonical_host("Пример.РФ") == "xn--e1afmkfd.xn--p1ai"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        42,
        ["example.ru"],
        "localhost",
        "www.ru",
        "ftp://example.ru",
        "file://example.ru/x",
        "https://",
        "https://user:secret@example.ru",
        "https://exa mple.ru",
        "https://example",
        "https://.ru",
        "https://-example.ru",
        "https://example-.ru",
        "https://exam_ple.ru",
        "https://example.ru\\path",
        "example.ru:99999",
        "javascript:alert(1)",
        "x" * 254,
    ],
)
def test_canonical_host_rejects_unusable_input(value):
    with pytest.raises(ValidationError):
        canonical_host(value)


def test_same_site_host_accepts_the_host_and_its_subdomains():
    assert same_site_host("example.ru", "example.ru") is True
    assert same_site_host("example.ru", "shop.example.ru") is True
    assert same_site_host("example.ru", "a.b.example.ru") is True
    assert same_site_host("example.ru", "WWW.Example.RU") is True
    assert same_site_host("example.ru", "shop.example.ru.") is True
    assert same_site_host("www.example.ru", "shop.example.ru") is True


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "example.com",
        "notexample.ru",
        "example.ru.attacker.test",
        "attacker.test",
        "shop.example.ru.attacker.test",
        "example-ru",
    ],
)
def test_same_site_host_rejects_lookalikes_and_other_domains(candidate):
    assert same_site_host("example.ru", candidate) is False


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "0.0.0.0",
        "::",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.1.1",
        "fe80::1",
        "224.0.0.1",
        "239.255.255.250",
        "ff02::1",
        "255.255.255.255",
        "240.0.0.1",
        "100.64.0.1",
        "192.0.2.1",
        "198.51.100.10",
        "203.0.113.7",
        "2001:db8::1",
        "fc00::1",
        "fec0::1",
        "::ffff:10.0.0.1",
        "localhost",
        "printer.local",
        "ns.internal",
        "example.com",
        "not an address",
        "",
    ],
)
def test_is_public_address_rejects_every_blocked_range_and_local_name(value):
    assert is_public_address(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "8.8.8.8",
        "93.184.216.34",
        "1.1.1.1",
        "2606:4700:4700::1111",
    ],
)
def test_is_public_address_accepts_a_public_address(value):
    assert is_public_address(value) is True


def test_the_fetch_limits_are_the_agreed_ones():
    assert MAX_FETCH_PAGES == 5
    assert MAX_FETCH_BYTES == 1024 * 1024
    assert FETCH_TOTAL_TIMEOUT == 60.0
    assert FETCH_CONNECT_TIMEOUT == 10.0
    assert MAX_FETCH_REDIRECTS == 5
    assert MAX_PAGE_TEXT_CHARS == 20_000


def test_a_fetched_page_carries_its_url_title_and_text():
    page = FetchedPage(url="https://example.ru/", title="Заголовок", text="Видимый текст")
    assert (page.url, page.title, page.text) == ("https://example.ru/", "Заголовок", "Видимый текст")
