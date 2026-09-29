"""SSRF-safe crawler for the public pages of one entered host.

Every connection is made only after its hostname has been resolved and every
returned address has been checked as public, and the request itself goes to that
verified address: the `Host` header and the TLS SNI name stay the entered
hostname, so a DNS answer that changes between the check and the connection
cannot move the socket. Redirects are followed manually, only within the entered
host and its subdomains, at most five times, and robots.txt is always obeyed.

The adapter owns no client and no secrets: it reuses the shared
`httpx.AsyncClient`, and tests inject both the transport and the resolver.
"""

from __future__ import annotations

import asyncio
import socket
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.errors import ProviderError, ValidationError
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

Resolver = Callable[[str], Awaitable[tuple[str, ...]]]

USER_AGENT = "ai-tracker-seo/1.0"
# robots.txt is always read for the wildcard group: the User-Agent is never
# changed to slip past a rule that is meant for this crawler.
ROBOTS_USER_AGENT = "*"
ALLOWED_SCHEMES = ("http", "https")
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template"})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
NON_PAGE_PREFIXES = ("mailto:", "tel:", "javascript:", "data:", "ftp:", "blob:")

FETCH_FAILED = "Не удалось загрузить сайт"
FETCH_UNREACHABLE = "Сайт не отвечает"
FETCH_REFUSED = "Сайт отклонил запрос"
FETCH_UNRESOLVED = "Не удалось определить адрес сайта"
FETCH_NOT_HTML = "Ответ сайта не является HTML-страницей"
FETCH_TIMEOUT = "Превышено время обхода сайта"
BLOCKED_ADDRESS = "Адрес сайта недоступен для безопасного обхода"
REDIRECT_REFUSED = "Перенаправление сайта отклонено"
ROBOTS_DISALLOWED = "Обход страницы запрещён robots.txt"


async def resolve_with_loop(host: str) -> tuple[str, ...]:
    """Resolve a hostname through the running loop; every test injects its own."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


class HttpxSiteFetcher:
    """The `SiteFetcher` port over a shared client, with pinned addresses."""

    def __init__(self, client: httpx.AsyncClient, *, resolver: Resolver | None = None) -> None:
        self.client = client
        self.resolver: Resolver = resolver if resolver is not None else resolve_with_loop

    async def fetch(self, host: str) -> tuple[FetchedPage, ...]:
        """Crawl the host and return the pages read.

        A page that fails is skipped, so a partial crawl returns what was read;
        a crawl that reads nothing raises a safe `ProviderError`.
        """
        start = canonical_host(host)
        pages: list[FetchedPage] = []
        try:
            async with asyncio.timeout(FETCH_TOTAL_TIMEOUT):
                await self._crawl(start, pages)
        except TimeoutError as exc:
            if not pages:
                raise ProviderError(FETCH_TIMEOUT) from exc
        return tuple(pages)

    async def _crawl(self, host: str, pages: list[FetchedPage]) -> None:
        """Breadth-first walk of same-host links; at most MAX_FETCH_PAGES URLs are requested."""
        robots = await self._robots(host)
        start = f"https://{host}/"
        queue: deque[str] = deque([start])
        seen = {start}
        refused: str | None = None
        attempts = 0
        while queue and attempts < MAX_FETCH_PAGES:
            attempts += 1
            url = queue.popleft()
            try:
                page, links = await self._read(host, url, robots)
            except _SkipPage as failure:
                refused = refused or failure.message
                continue
            pages.append(page)
            for link in links:
                if link not in seen:
                    seen.add(link)
                    queue.append(link)
        if not pages:
            raise ProviderError(refused or FETCH_FAILED)

    async def _robots(self, host: str) -> RobotFileParser | None:
        """Read robots.txt; a missing, unreachable, or non-200 file allows the crawl."""
        url = f"https://{host}/robots.txt"
        try:
            response = await self._follow(host, url, None)
        except _SkipPage:
            return None
        if not 200 <= response.status_code < 300:
            return None
        parser = RobotFileParser()
        parser.set_url(url)
        parser.parse(_decode(response.body, response.content_type).splitlines())
        return parser

    async def _read(
        self,
        host: str,
        url: str,
        robots: RobotFileParser | None,
    ) -> tuple[FetchedPage, tuple[str, ...]]:
        """Read one URL into a page; a skipped URL carries the reason it was skipped.

        The refusal of the site is named for the operator and the model: an HTTP
        status that is not a success, a response that is not HTML, or a transport
        failure each become their own safe message. No upstream body is quoted.
        """
        response = await self._follow(host, url, robots)
        if not 200 <= response.status_code < 300:
            raise _SkipPage(f"{FETCH_REFUSED} ({response.status_code})")
        if not _is_html(response.content_type):
            raise _SkipPage(FETCH_NOT_HTML)
        title, text, links = _extract(_decode(response.body, response.content_type))
        page = FetchedPage(
            url=response.url,
            title=title[:MAX_PAGE_TEXT_CHARS],
            text=text[:MAX_PAGE_TEXT_CHARS],
        )
        return page, _same_site_links(host, response.url, links)

    async def _follow(self, host: str, url: str, robots: RobotFileParser | None) -> _Response:
        """Request a URL, following only same-site redirects and at most five of them."""
        current = url
        for hop in range(MAX_FETCH_REDIRECTS + 1):
            if robots is not None and not robots.can_fetch(ROBOTS_USER_AGENT, current):
                raise _SkipPage(ROBOTS_DISALLOWED)
            response = await self._request(current)
            if response.status_code not in REDIRECT_STATUSES:
                return response
            if hop >= MAX_FETCH_REDIRECTS or not response.location:
                raise _SkipPage(REDIRECT_REFUSED)
            target = _same_site_url(host, current, response.location)
            if target is None:
                raise _SkipPage(REDIRECT_REFUSED)
            current = target
        raise _SkipPage(REDIRECT_REFUSED)

    async def _request(self, url: str) -> _Response:
        """Connect to the verified address of the URL host, never to its unresolved name.

        The host of the current URL is resolved and checked at every hop, so a
        redirect to another same-site name is verified on its own.
        """
        host = _url_host(url)
        if not host:
            raise _SkipPage(FETCH_FAILED)
        address = await self._verified_address(host)
        timeout = httpx.Timeout(
            connect=FETCH_CONNECT_TIMEOUT,
            read=FETCH_TOTAL_TIMEOUT,
            write=FETCH_CONNECT_TIMEOUT,
            pool=FETCH_CONNECT_TIMEOUT,
        )
        headers = {
            "Host": _netloc(urlsplit(url)),
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            async with self.client.stream(
                "GET",
                _pinned_url(url, address),
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
                extensions={"sni_hostname": host},
            ) as response:
                body = await _read_bounded(response)
                return _Response(
                    url=url,
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type", ""),
                    location=response.headers.get("location"),
                    body=body,
                )
        except httpx.HTTPError as exc:
            # A refused connection, a timeout, or a broken transport mean the
            # same thing for the caller: the site did not answer.
            raise _SkipPage(FETCH_UNREACHABLE) from exc

    async def _verified_address(self, host: str) -> str:
        """Resolve a host and refuse it unless every address is public."""
        try:
            addresses = await self.resolver(host)
        except OSError as exc:
            raise _SkipPage(FETCH_UNRESOLVED) from exc
        if not addresses:
            raise _SkipPage(FETCH_UNRESOLVED)
        for address in addresses:
            if not is_public_address(address):
                raise _SkipPage(BLOCKED_ADDRESS)
        return addresses[0]


@dataclass(frozen=True)
class _Response:
    """The parts of one HTTP response the crawler still needs."""

    url: str
    status_code: int
    content_type: str
    location: str | None
    body: bytes


class _SkipPage(Exception):
    """A page-level failure: the URL is skipped, the crawl itself continues."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _HtmlExtractor(HTMLParser):
    """Collects the title, the visible text, and the link targets of one document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skipped: list[str] = []
        self._in_title = False
        self._title: list[str] = []
        self._text: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skipped.append(tag)
            return
        if self._skipped:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS:
            if self._skipped and self._skipped[-1] == tag:
                self._skipped.pop()
            return
        if self._skipped:
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skipped or not data.strip():
            return
        if self._in_title:
            self._title.append(data)
        else:
            self._text.append(data)

    def title(self) -> str:
        return " ".join("".join(self._title).split())

    def text(self) -> str:
        return " ".join(" ".join(self._text).split())


def _extract(html: str) -> tuple[str, str, tuple[str, ...]]:
    """Return the title, visible text, and raw `href` values of one HTML document."""
    parser = _HtmlExtractor()
    parser.feed(html)
    parser.close()
    return parser.title(), parser.text(), tuple(parser.links)


async def _read_bounded(response: httpx.Response) -> bytes:
    """Read at most `MAX_FETCH_BYTES` of a response body and stop pulling more."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        remaining = MAX_FETCH_BYTES - len(body)
        if remaining <= 0:
            break
        body.extend(chunk[:remaining])
        if len(body) >= MAX_FETCH_BYTES:
            break
    return bytes(body)


def _is_html(content_type: str) -> bool:
    """Only an HTML or XHTML response counts as a page; robots.txt is read apart."""
    return content_type.split(";", 1)[0].strip().lower() in HTML_CONTENT_TYPES


def _decode(body: bytes, content_type: str) -> str:
    """Decode a response with the charset it declares, falling back to UTF-8."""
    charset = _charset(content_type)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _charset(content_type: str) -> str:
    for parameter in content_type.split(";")[1:]:
        name, _, value = parameter.partition("=")
        if name.strip().lower() == "charset":
            return value.strip().strip("\"'") or "utf-8"
    return "utf-8"


def _netloc(parts: SplitResult) -> str:
    """The lowercase `host[:port]` of a URL, safe for a `Host` header."""
    host = (parts.hostname or "").rstrip(".").lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{parts.port}" if parts.port is not None else host


def _url_host(url: str) -> str:
    """The hostname a request must be verified and named by: Host and TLS SNI agree."""
    return (urlsplit(url).hostname or "").rstrip(".").lower()


def _pinned_url(url: str, address: str) -> str:
    """Rewrite a URL to the verified address, keeping scheme, path, query, and port."""
    parts = urlsplit(url)
    netloc = f"[{address}]" if ":" in address else address
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _same_site_url(host: str, base: str, href: str) -> str | None:
    """Return the absolute HTTP(S) URL of a link on the host or its subdomains."""
    value = href.strip()
    if not value or value.startswith("#") or value.lower().startswith(NON_PAGE_PREFIXES):
        return None
    try:
        absolute = urljoin(base, value)
        parts = urlsplit(absolute)
        netloc = _netloc(parts)
    except ValueError:
        return None
    if parts.scheme not in ALLOWED_SCHEMES:
        return None
    try:
        link_host = canonical_host(absolute)
    except ValidationError:
        return None
    if not same_site_host(host, link_host):
        return None
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _same_site_links(host: str, base: str, links: Iterable[str]) -> tuple[str, ...]:
    """Absolute, deduplicated, same-site links of one page, without fragments."""
    targets: list[str] = []
    for link in links:
        target = _same_site_url(host, base, link)
        if target is not None and target not in targets:
            targets.append(target)
    return tuple(targets)
