"""Structured SEO answers and safe source URLs, independent of providers."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.core.errors import ValidationError
from app.domain.endpoints import BLOCKED_SUFFIXES
from app.domain.site_fetch import (
    LOCAL_NAME_SUFFIXES,
    LOCAL_NAMES,
    canonical_host,
    is_public_address,
)

AnswerMode = Literal["text", "deepseek_web"]
SearchStatus = Literal["not_requested", "completed", "error"]


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str | None


@dataclass(frozen=True)
class Citation:
    url: str
    title: str | None
    cited_text: str | None
    block_index: int
    order: int


@dataclass(frozen=True)
class SeoAnswer:
    text: str
    answer_mode: AnswerMode
    search_status: SearchStatus
    search_results: tuple[SearchResult, ...]
    citations: tuple[Citation, ...]
    model: str
    search_calls: int | None


@dataclass(frozen=True)
class SeoConnectionSnapshot:
    connection_id: str
    name: str
    kind: str
    endpoint: str
    model: str
    answer_mode: AnswerMode
    thinking_disabled: bool


class SeoAnswerProvider(Protocol):
    def answer(self, prompt: str) -> SeoAnswer: ...
    def close(self) -> None: ...


def answer_from_dict(value: object) -> SeoAnswer:
    """Validate persisted evidence rather than treating corruption as no citations."""
    if not isinstance(value, dict):
        raise ValidationError("Некорректные данные источников")
    try:
        result = SeoAnswer(**{**value,
            "search_results": tuple(SearchResult(**item) for item in value["search_results"]),
            "citations": tuple(Citation(**item) for item in value["citations"]),
        })
        if (result.answer_mode not in ("text", "deepseek_web")
            or result.search_status not in ("not_requested", "completed", "error")
            or not isinstance(result.text, str) or not isinstance(result.model, str)
            or (result.search_calls is not None and (type(result.search_calls) is not int or result.search_calls < 0))):
            raise ValueError
        for item in (*result.search_results, *result.citations):
            if normalize_source_url(item.url) is None or (item.title is not None and not isinstance(item.title, str)):
                raise ValueError
        for item in result.citations:
            if (type(item.block_index) is not int or item.block_index < 0 or type(item.order) is not int or item.order < 1
                or (item.cited_text is not None and not isinstance(item.cited_text, str))):
                raise ValueError
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Некорректные данные источников") from exc


def normalize_source_url(value: object) -> str | None:
    """Validate a public-looking URL without resolving or fetching its host.

    DNS publicness cannot be proved without a network lookup. These links are
    displayed only, never fetched server-side, so reject known local names and
    private IPs and keep the same hostname validation as the crawler.
    """
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    if "\\" in value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if parsed.scheme not in ("http", "https") or not host or parsed.username is not None or parsed.password is not None:
            return None
        host = host.rstrip(".").lower()
        if host in LOCAL_NAMES or host.endswith((*LOCAL_NAME_SUFFIXES, *BLOCKED_SUFFIXES)):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            canonical_host(value)
            host = host.encode("idna").decode("ascii")
        else:
            if not is_public_address(host):
                return None
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc += f":{port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
    except (ValueError, UnicodeError, ValidationError):
        return None


def normalize_sources(
    results: Sequence[SearchResult], citations: Sequence[Citation],
) -> tuple[tuple[SearchResult, ...], tuple[Citation, ...]]:
    pages: dict[str, SearchResult] = {}
    for result in results:
        url = normalize_source_url(result.url)
        if url is not None and url not in pages:
            pages[url] = replace(result, url=url)
    accepted: list[Citation] = []
    for citation in citations:
        url = normalize_source_url(citation.url)
        if url is not None:
            title = citation.title or (pages[url].title if url in pages else None)
            accepted.append(replace(citation, url=url, title=title))
    return tuple(pages.values()), tuple(accepted)
