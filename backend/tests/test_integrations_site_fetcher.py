"""The SSRF-safe site fetcher over `httpx.MockTransport` and an injected resolver.

Every request goes to a hostname resolved by the injected resolver and travels
through a mock transport, so the suite never performs DNS or a real connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.errors import ProviderError
from app.domain.site_fetch import (
    FETCH_CONNECT_TIMEOUT,
    MAX_FETCH_PAGES,
    MAX_PAGE_TEXT_CHARS,
)
from app.integrations import site_fetcher as site_fetcher_module
from app.integrations.site_fetcher import (
    BLOCKED_ADDRESS,
    FETCH_NOT_HTML,
    FETCH_REFUSED,
    FETCH_TIMEOUT,
    FETCH_UNREACHABLE,
    FETCH_UNRESOLVED,
    MAX_FETCH_RETRIES,
    REDIRECT_REFUSED,
    RETRY_BACKOFF_SECONDS,
    HttpxSiteFetcher,
)

PUBLIC_IP = "93.184.216.34"
PRIVATE_IP = "127.0.0.1"

Route = httpx.Response | Callable[[httpx.Request], httpx.Response]


async def public_resolver(host: str) -> tuple[str, ...]:
    """Resolve every hostname to one public address, without touching DNS."""
    return (PUBLIC_IP,)


class Site:
    """A fake site keyed by `host/path` (or by path alone); it records requests."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(f"{request.headers['host']}{self._path(request)}")
        if route is None:
            route = self.routes.get(self._path(request))
        if route is None:
            return httpx.Response(404, content=b"missing", headers={"Content-Type": "text/html"})
        return route(request) if callable(route) else route

    @staticmethod
    def _path(request: httpx.Request) -> str:
        query = request.url.query.decode()
        return f"{request.url.path}?{query}" if query else request.url.path

    @property
    def paths(self) -> list[str]:
        return [self._path(request) for request in self.requests]

    @property
    def hosts(self) -> list[str]:
        return [request.headers["host"] for request in self.requests]


@asynccontextmanager
async def build(
    handler: Callable[[httpx.Request], object],
    resolver: Callable | None = None,
    sleep: Callable | None = None,
):
    """A fetcher over a mock transport, closed when the test leaves the block."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield HttpxSiteFetcher(client, resolver=resolver or public_resolver, sleep=sleep)
    finally:
        await client.aclose()


def body_page(body: str, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(200, content=body.encode("utf-8"), headers={"Content-Type": content_type})


async def no_sleep(_seconds: float) -> None:
    """The default pause of a test: the real one is asserted, never spent."""


def links(*hrefs: str, title: str = "Заголовок") -> httpx.Response:
    anchors = "".join(f'<a href="{href}">ссылка</a>' for href in hrefs)
    return body_page(f"<html><head><title>{title}</title></head><body>{anchors}<p>Видимый текст</p></body></html>")


def redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


@pytest.mark.anyio
async def test_it_connects_to_the_verified_address_with_the_host_header_and_sni():
    site = Site({"/robots.txt": httpx.Response(404), "/": links("/about"), "/about": links("/")})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("https://Example.ru/")

    assert [page.url for page in pages] == ["https://example.ru/", "https://example.ru/about"]
    assert pages[0].title == "Заголовок"
    assert "Видимый текст" in pages[0].text

    request = site.requests[1]
    assert request.url.host == PUBLIC_IP
    assert request.url.scheme == "https"
    assert request.headers["host"] == "example.ru"
    assert request.extensions["sni_hostname"] == "example.ru"
    assert request.extensions["timeout"]["connect"] == FETCH_CONNECT_TIMEOUT


@pytest.mark.anyio
async def test_it_crawls_the_entered_host_and_its_subdomains_only():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": links(
            "/about",
            "https://shop.example.ru/",
            "https://other.test/",
            "https://example.ru.attacker.test/",
            "https://notexample.ru/",
            "mailto:hello@example.ru",
            "tel:+70000000000",
            "javascript:alert(1)",
            "ftp://example.ru/file",
            "data:text/html,<p>x</p>",
        ),
        "/about": body_page("<p>О нас</p>"),
        "shop.example.ru/": body_page("<p>Магазин</p>"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == [
        "https://example.ru/",
        "https://example.ru/about",
        "https://shop.example.ru/",
    ]
    assert set(site.hosts) == {"example.ru", "shop.example.ru"}


@pytest.mark.anyio
async def test_it_deduplicates_links_without_fragments_and_keeps_the_query():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": links("/about", "https://example.ru/about", "https://EXAMPLE.ru/about#top", "/about?page=2"),
        "/about": body_page("<p>О нас</p>"),
        "/about?page=2": body_page("<p>Страница два</p>"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("https://example.ru/#start")

    assert [page.url for page in pages] == [
        "https://example.ru/",
        "https://example.ru/about",
        "https://example.ru/about?page=2",
    ]


@pytest.mark.anyio
async def test_it_stops_after_twenty_pages():
    routes: dict[str, Route] = {"/robots.txt": httpx.Response(404), "/": links("/p1")}
    for index in range(1, 40):
        routes[f"/p{index}"] = links(f"/p{index + 1}")
    site = Site(routes)

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert len(pages) == MAX_FETCH_PAGES
    assert pages[-1].url == "https://example.ru/p19"
    assert len(site.paths) == MAX_FETCH_PAGES + 1  # robots.txt and twenty pages
    assert "/p20" not in site.paths


@pytest.mark.anyio
async def test_it_truncates_a_response_at_one_megabyte():
    # The filler is an absolute size, not `MAX_FETCH_BYTES`: widening the cap
    # must make this test fail instead of moving the marker out of reach.
    filler = "x" * (1024 * 1024 + 4096)
    body = f"<title>Начало</title><p>Начало</p><!--{filler}--><title>Позже</title><p>Позже</p>"
    site = Site({"/robots.txt": httpx.Response(404), "/": body_page(body)})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert pages[0].title == "Начало"
    assert "Начало" in pages[0].text
    assert "Позже" not in pages[0].text


@pytest.mark.anyio
async def test_it_cuts_page_text_at_twenty_thousand_characters():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": body_page("<p>" + "а" * 30_000 + "</p>"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert len(pages[0].text) == 20_000
    assert len(pages[0].text) == MAX_PAGE_TEXT_CHARS


@pytest.mark.anyio
async def test_it_ignores_scripts_styles_and_forms():
    body = (
        "<html><head><title>Заголовок</title>"
        "<script src='/evil.js'>var secret = 'script-token';</script>"
        "<style>.notice { color: red }</style></head>"
        "<body><noscript>noscript-token</noscript><template>template-token</template>"
        "<form action='/submit'><input name='field' value='form-token'></form>"
        "<p>Видимый&nbsp;текст</p><a href='javascript:alert(1)'>нажми</a></body></html>"
    )
    site = Site({"/robots.txt": httpx.Response(404), "/": body_page(body)})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert pages[0].title == "Заголовок"
    assert "Видимый текст" in pages[0].text
    for token in ("script-token", "noscript-token", "template-token", "form-token", "color: red"):
        assert token not in pages[0].text
    assert site.paths == ["/robots.txt", "/"]


@pytest.mark.anyio
async def test_a_page_without_a_title_has_an_empty_title():
    site = Site({"/robots.txt": httpx.Response(404), "/": body_page("<p>Без заголовка</p>")})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert pages[0].title == ""


@pytest.mark.anyio
async def test_only_html_responses_become_pages():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": links("/file.pdf", "/no-type", "/open", "/xhtml"),
        "/file.pdf": httpx.Response(200, content=b"%PDF-1.4 secret", headers={"Content-Type": "application/pdf"}),
        "/no-type": httpx.Response(200, content=b"<p>no content type</p>"),
        "/open": body_page("<p>Открыто</p>"),
        "/xhtml": body_page("<p>XHTML</p>", "application/xhtml+xml"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == [
        "https://example.ru/",
        "https://example.ru/open",
        "https://example.ru/xhtml",
    ]
    assert "secret" not in "".join(page.text for page in pages)


@pytest.mark.anyio
async def test_every_connection_resolves_the_host_and_uses_the_same_user_agent():
    asked: list[str] = []

    async def resolver(host: str) -> tuple[str, ...]:
        asked.append(host)
        return (PUBLIC_IP,)

    site = Site({"/robots.txt": httpx.Response(404), "/": links("/about"), "/about": body_page("<p>О нас</p>")})

    async with build(site, resolver) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert len(pages) == 2
    assert asked == ["example.ru", "example.ru", "example.ru"]  # robots.txt and both pages
    assert {request.headers["user-agent"] for request in site.requests} == {site_fetcher_module.USER_AGENT}


@pytest.mark.anyio
async def test_a_failed_page_keeps_the_pages_already_read():
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow page")

    site = Site({"/robots.txt": httpx.Response(404), "/": links("/broken", "/open"), "/broken": broken, "/open": body_page("<p>Открыто</p>")})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/", "https://example.ru/open"]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_refusing_start_page_names_its_status_safely(status):
    """A rate limit or a server error is reported with its code, never its body."""
    site = Site({"/": httpx.Response(status, content=b"secret stack trace")})

    async with build(site, sleep=no_sleep) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == f"{FETCH_REFUSED} ({status})"
    assert "secret" not in str(raised.value)


@pytest.mark.anyio
async def test_a_non_html_start_page_is_reported_as_such():
    site = Site({"/": httpx.Response(200, content=b"%PDF-1.4 secret", headers={"Content-Type": "application/pdf"})})

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_NOT_HTML
    assert "secret" not in str(raised.value)


@pytest.mark.anyio
async def test_a_transport_failure_on_the_start_page_is_a_safe_error():
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with build(Site({"/": broken})) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_UNREACHABLE
    assert "connection refused" not in str(raised.value)


@pytest.mark.anyio
async def test_a_connect_timeout_on_the_start_page_is_a_safe_error():
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out")

    async with build(Site({"/": broken})) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_UNREACHABLE
    assert "timed out" not in str(raised.value)


@pytest.mark.anyio
async def test_a_host_that_does_not_resolve_is_reported_safely():
    async def resolver(host: str) -> tuple[str, ...]:
        raise OSError("no such host")

    async with build(Site({"/": body_page("<p>Привет</p>")}), resolver) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_UNRESOLVED
    assert "no such host" not in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("93.184.216.34", "10.0.0.1")])
async def test_a_non_public_address_is_refused_before_any_request(addresses):
    async def resolver(host: str) -> tuple[str, ...]:
        return addresses

    site = Site({"/": links("/about"), "/about": body_page("<p>О нас</p>")})

    async with build(site, resolver) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == BLOCKED_ADDRESS
    assert site.requests == []


@pytest.mark.anyio
async def test_the_total_timeout_stops_a_slow_crawl(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(site_fetcher_module, "FETCH_TOTAL_TIMEOUT", 0.3)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return body_page("<p>Никогда</p>")

    site = Site({"/robots.txt": httpx.Response(404), "/": slow})

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_TIMEOUT


@pytest.mark.anyio
async def test_the_total_timeout_covers_robots_txt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(site_fetcher_module, "FETCH_TOTAL_TIMEOUT", 0.3)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return body_page("User-agent: *\nDisallow: /\n", "text/plain")

    site = Site({"/robots.txt": slow, "/": body_page("<p>Никогда</p>")})

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_TIMEOUT
    assert site.paths == ["/robots.txt"]


@pytest.mark.anyio
async def test_the_total_timeout_returns_the_pages_already_read(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(site_fetcher_module, "FETCH_TOTAL_TIMEOUT", 0.3)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return body_page("<p>Никогда</p>")

    site = Site({"/robots.txt": httpx.Response(404), "/": links("/slow"), "/slow": slow})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/"]


@pytest.mark.anyio
async def test_it_follows_at_most_five_redirects():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": redirect("/r1"),
        "/r1": redirect("/r2"),
        "/r2": redirect("/r3"),
        "/r3": redirect("/r4"),
        "/r4": redirect("/r5"),
        "/r5": body_page("<p>Финиш</p>"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/r5"]


@pytest.mark.anyio
async def test_the_sixth_redirect_is_refused():
    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": redirect("/r1"),
        "/r1": redirect("/r2"),
        "/r2": redirect("/r3"),
        "/r3": redirect("/r4"),
        "/r4": redirect("/r5"),
        "/r5": redirect("/r6"),
        "/r6": body_page("<p>Слишком далеко</p>"),
    })

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == REDIRECT_REFUSED
    assert "/r6" not in site.paths
    assert "/r5" in site.paths


@pytest.mark.anyio
async def test_a_redirect_without_a_location_is_refused():
    site = Site({"/robots.txt": httpx.Response(404), "/": httpx.Response(302)})

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == REDIRECT_REFUSED


@pytest.mark.anyio
@pytest.mark.parametrize(
    "location",
    [
        "https://evil.test/",
        "https://example.ru.attacker.test/",
        "https://notexample.ru/",
        "//evil.test/path",
    ],
)
async def test_a_cross_host_redirect_is_refused(location):
    site = Site({"/robots.txt": httpx.Response(404), "/": redirect(location)})

    async with build(site) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == REDIRECT_REFUSED
    assert set(site.hosts) == {"example.ru"}


@pytest.mark.anyio
async def test_the_address_is_checked_again_after_a_redirect():
    async def resolver(host: str) -> tuple[str, ...]:
        return (PUBLIC_IP,) if host == "example.ru" else (PRIVATE_IP,)

    site = Site({"/robots.txt": httpx.Response(404), "/": redirect("https://cdn.example.ru/")})

    async with build(site, resolver) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == BLOCKED_ADDRESS
    assert "cdn.example.ru" not in site.hosts


@pytest.mark.anyio
async def test_a_second_resolution_that_turns_private_is_refused():
    answers = [(PUBLIC_IP,), (PUBLIC_IP,), (PRIVATE_IP,)]

    async def resolver(host: str) -> tuple[str, ...]:
        return answers.pop(0) if answers else (PRIVATE_IP,)

    site = Site({
        "/robots.txt": httpx.Response(404),
        "/": links("/about"),
        "/about": links("/more"),
        "/more": body_page("<p>Дальше</p>"),
    })

    async with build(site, resolver) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/"]
    assert all(request.url.host == PUBLIC_IP for request in site.requests)
    assert "/about" not in site.paths


@pytest.mark.anyio
async def test_a_url_disallowed_by_robots_is_not_crawled():
    site = Site({
        "/robots.txt": body_page("User-agent: *\nDisallow: /private\n", "text/plain"),
        "/": links("/private", "/open"),
        "/private": body_page("<p>Секрет</p>"),
        "/open": body_page("<p>Открыто</p>"),
    })

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/", "https://example.ru/open"]
    assert "/private" not in site.paths


@pytest.mark.anyio
async def test_robots_can_disallow_the_whole_site():
    site = Site({
        "/robots.txt": body_page("User-agent: *\nDisallow: /\n", "text/plain"),
        "/": links("/open"),
        "/open": body_page("<p>Открыто</p>"),
    })

    async with build(site) as fetcher:
        with pytest.raises(ProviderError):
            await fetcher.fetch("example.ru")

    assert site.paths == ["/robots.txt"]


@pytest.mark.anyio
async def test_a_missing_robots_file_does_not_block_the_crawl():
    site = Site({"/": links("/open"), "/open": body_page("<p>Открыто</p>")})

    async with build(site) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/", "https://example.ru/open"]


@pytest.mark.anyio
async def test_an_unreachable_robots_file_does_not_block_the_crawl():
    site = Site({"/": links("/open"), "/open": body_page("<p>Открыто</p>")})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            raise httpx.ConnectError("robots unreachable")
        return site(request)

    async with build(handler) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.url for page in pages] == ["https://example.ru/", "https://example.ru/open"]


# -- one page, several addresses, and a site that asks for patience -----------
#
# A host commonly answers on several addresses, and they are not equal: a
# dual-stack name in a host without an IPv6 route, or one broken replica, would
# otherwise lose the page — and a lost entry page loses the whole run, because a
# crawl that read nothing is a fatal site failure. A `429`/`503` answer is not a
# dead end either: it asks for a slower client, and repeating the URL a couple of
# times after a pause is what a polite crawler does with it.

SECOND_IP = "93.184.216.35"


@pytest.mark.anyio
async def test_a_page_is_read_from_the_next_address_when_the_first_one_fails():
    async def resolver(_host: str) -> tuple[str, ...]:
        return (PUBLIC_IP, SECOND_IP)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == PUBLIC_IP:
            raise httpx.ConnectError("no route to this address", request=request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return body_page("<html><head><title>Второй адрес</title></head><body>ok</body></html>")

    async with build(handler, resolver=resolver) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.title for page in pages] == ["Второй адрес"]


@pytest.mark.anyio
async def test_a_page_no_address_answers_is_still_unreachable():
    """The fallback never hides a site that is simply down."""
    async def resolver(_host: str) -> tuple[str, ...]:
        return (PUBLIC_IP, SECOND_IP)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to this address", request=request)

    async with build(handler, resolver=resolver) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == FETCH_UNREACHABLE


@pytest.mark.anyio
async def test_a_slow_down_answer_is_repeated_after_the_pause_it_asks_for():
    slept: list[float] = []
    answers: list[int] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        answers.append(len(answers) + 1)
        if len(answers) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, content=b"slow down")
        return body_page("<html><head><title>Со второй попытки</title></head><body>ok</body></html>")

    async with build(handler, sleep=sleep) as fetcher:
        pages = await fetcher.fetch("example.ru")

    assert [page.title for page in pages] == ["Со второй попытки"]
    assert len(answers) == 2
    assert slept == [2.0]


@pytest.mark.anyio
async def test_a_permanent_slow_down_stops_after_the_bounded_retries():
    """The pause grows per attempt, and the last answer keeps its status."""
    slept: list[float] = []
    calls = 0

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        return httpx.Response(503, content=b"unavailable")

    async with build(handler, sleep=sleep) as fetcher:
        with pytest.raises(ProviderError) as raised:
            await fetcher.fetch("example.ru")

    assert str(raised.value) == f"{FETCH_REFUSED} (503)"
    assert calls == MAX_FETCH_RETRIES + 1
    assert slept == [RETRY_BACKOFF_SECONDS, RETRY_BACKOFF_SECONDS * 2]
