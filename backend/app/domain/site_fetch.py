"""Host, address, and limit rules of the SSRF-safe public site fetcher.

The SEO flow enters one public HTTP(S) URL and crawls only that host and its
subdomains, so the host rules live here and are imported by the request
normalizer (Task 3) and the orchestrator (Task 5) instead of being repeated.
Nothing in this module performs I/O: the adapter resolves and connects.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import ValidationError
from app.domain.search import INVALID_SITE, normalize_search_host

# Crawl bounds: at most five pages of the entered host, 1 MiB per response, five
# redirects per request, and 60 seconds for the whole crawl including robots.txt.
MAX_FETCH_PAGES = 5
MAX_FETCH_BYTES = 1024 * 1024
FETCH_TOTAL_TIMEOUT = 60.0
FETCH_CONNECT_TIMEOUT = 10.0
MAX_FETCH_REDIRECTS = 5

# Page text is sent to the configured service LLM, so every page is cut to a
# fixed length: five pages must not turn into tens of megabytes of prompt text.
MAX_PAGE_TEXT_CHARS = 20_000

LOCAL_NAMES = frozenset({"localhost", "local", "localdomain"})
LOCAL_NAME_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal", ".home.arpa")


@dataclass(frozen=True)
class FetchedPage:
    """One crawled page: its URL, HTML title, and visible text."""

    url: str
    title: str
    text: str


class SiteFetcher(Protocol):
    """Outbound port: read the public pages of one host without network surprises."""

    async def fetch(self, host: str) -> tuple[FetchedPage, ...]: ...


def canonical_host(value: object) -> str:
    """Return the canonical host of a URL or bare host, or raise ValidationError.

    The result is lowercase ASCII: the trailing dot and a leading `www.` are
    dropped, so every rule built on it compares one spelling of a site.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(INVALID_SITE)
    host = normalize_search_host(value.strip())
    canonical = host.removeprefix("www.")
    if "." not in canonical:
        raise ValidationError(INVALID_SITE)
    return canonical


def same_site_host(target: str, candidate: str) -> bool:
    """Report whether two names are the same host or the candidate is a subdomain.

    A lookalike such as `example.ru.attacker.test` never matches `example.ru`, and
    a dropped leading `www.` never hides the difference.
    """
    host = _bare_host(target)
    other = _bare_host(candidate)
    if not host or not other:
        return False
    return other == host or other.endswith(f".{host}")


def is_public_address(value: str) -> bool:
    """Report whether a value is a public IP literal.

    Loopback, private, link-local, multicast, reserved, unspecified, site-local,
    shared, and local names are refused; anything that is not an IP literal is
    refused as well, because a name is not an address that was checked.
    """
    if not isinstance(value, str):
        return False
    host = value.strip().strip("[]").rstrip(".").lower()
    if not host or host in LOCAL_NAMES or host.endswith(LOCAL_NAME_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return False
    return address.is_global


def _bare_host(value: str) -> str:
    """Lowercase a host name, dropping its trailing dot and a leading `www.`."""
    if not isinstance(value, str):
        return ""
    host = value.strip().rstrip(".").lower()
    return host.removeprefix("www.")
