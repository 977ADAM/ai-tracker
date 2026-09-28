"""Pure SEO rules: the request, service merge, candidates, and generated queries.

The SEO flow has its own limits and its own request normalizer: the old
`LIMITS` dictionary and `domain.requests` keep serving `/api/check`, and the
host rules come from `domain.site_fetch.canonical_host` / `same_site_host`
instead of being repeated here.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.core.errors import ValidationError
from app.domain.matching import mentions_phrase, normalize_text
from app.domain.search import INVALID_SITE, TOP_RESULTS, result_url_host
from app.domain.seo_llm import parse_json_object
from app.domain.site_fetch import canonical_host, same_site_host

# Fixed SEO constants: the form has no limit field and the old 20-query
# validators of `/api/check`, `/api/search`, and `/api/runs` stay untouched.
# Revision 2 raises the generated-query cap to 40 and the run estimate becomes
# `3 + 40` searches and `40 × M` model answers.
GENERATED_QUERY_LIMIT = 40
MIN_GENERATED_QUERIES = 5
QUERY_CATEGORIES = ("commercial", "informational", "comparative")
CATEGORY_LABELS = {
    "commercial": "Коммерческие",
    "informational": "Информационные",
    "comparative": "Сравнительные",
}
MAX_QUERY_LENGTH = 400
MAX_QUERY_WORDS = 40

# The six agents of the supervised run, in the order every read reports them.
# This module is the single source of the vocabulary: `domain.seo_tools` and
# `db.seo` import these names instead of repeating the tuple and the literal.
AGENTS = ("supervisor", "site", "competitors", "queries", "checks", "report")
AGENT_LABELS: Mapping[str, str] = {
    "supervisor": "Супервизор",
    "site": "Агент сайта",
    "competitors": "Агент конкурентов",
    "queries": "Агент запросов",
    "checks": "Агент проверок",
    "report": "Агент отчёта",
}
AgentStatus = Literal["pending", "running", "waiting", "done", "error", "skipped"]

SEED_COUNT = 3
MAX_SPHERE_LENGTH = 200
MAX_SERVICES = 20
MAX_SERVICE_LENGTH = 100
MAX_CONNECTIONS = 5
MAX_URL_LENGTH = 2048

ALLOWED_REQUEST_FIELDS = frozenset({"url", "sphere", "seeds", "services", "connection_ids"})

INVALID_REQUEST = "Некорректный запрос"
INVALID_SPHERE = f"Укажите сферу бизнеса длиной до {MAX_SPHERE_LENGTH} символов"
INVALID_SEEDS = f"Укажите ровно {SEED_COUNT} разных ключевых запроса"
INVALID_SEED_LIMITS = (
    f"Ключевой запрос должен содержать не более {MAX_QUERY_LENGTH} символов и {MAX_QUERY_WORDS} слов"
)
INVALID_SERVICES = f"Укажите от 1 до {MAX_SERVICES} разных услуг длиной до {MAX_SERVICE_LENGTH} символов"
INVALID_CONNECTIONS = f"Выберите от 1 до {MAX_CONNECTIONS} разных подключений моделей"
INVALID_HOST_IP = "Укажите адрес сайта доменом, а не IP"
INVALID_GENERATED = "Модель вернула некорректный список запросов"
INVALID_GENERATED_CATEGORY = "Модель вернула запрос с неизвестной категорией"
INVALID_GENERATED_LIMITS = (
    f"Сгенерированный запрос должен содержать не более {MAX_QUERY_LENGTH} символов и {MAX_QUERY_WORDS} слов"
)
TOO_FEW_GENERATED = f"Модель сгенерировала меньше {MIN_GENERATED_QUERIES} уникальных запросов"

_HOST_PATTERN = r"(?<!\w)(?:www\.)?{}\b"


@dataclass(frozen=True)
class SeoInput:
    """A normalized SEO request: the entered URL, its host, and the paid-run scope."""

    url: str
    host: str
    sphere: str
    seeds: tuple[str, ...]
    services: tuple[str, ...]
    connection_ids: tuple[str, ...]


def normalize_seo_request(payload: object) -> SeoInput:
    """Validate the URL, sphere, three key queries, services, and 1..5 connections.

    Exactly the five documented fields are accepted; an unknown field is a
    malformed request. The host is canonicalized with the fetcher rules, so a
    trailing dot and a leading `www.` never reach the crawl.
    """
    if not isinstance(payload, dict):
        raise ValidationError(INVALID_REQUEST)
    if any(not isinstance(key, str) or key not in ALLOWED_REQUEST_FIELDS for key in payload):
        raise ValidationError(INVALID_REQUEST)

    url = payload.get("url")
    if not isinstance(url, str) or not url.strip() or len(url.strip()) > MAX_URL_LENGTH:
        raise ValidationError(INVALID_SITE)
    site = url.strip()
    host = canonical_host(site)
    if _is_ip_literal(host):
        # A private address must never reach the crawler; only domains are accepted.
        raise ValidationError(INVALID_HOST_IP)

    sphere = payload.get("sphere")
    if not isinstance(sphere, str) or not 1 <= len(sphere.strip()) <= MAX_SPHERE_LENGTH:
        raise ValidationError(INVALID_SPHERE)

    return SeoInput(
        url=site,
        host=host,
        sphere=sphere.strip(),
        seeds=_normalize_seeds(payload.get("seeds")),
        services=_normalize_services(payload.get("services")),
        connection_ids=_normalize_connection_ids(payload.get("connection_ids")),
    )


def hosts_match(target: str, candidate: str) -> bool:
    """Report whether two names are the same site, ignoring `www.` and casing.

    Both arguments may be a bare host or an HTTP(S) URL; the URL form is parsed
    with the Yandex result rules and the comparison reuses `same_site_host`.
    """
    left = _host_of(target)
    right = _host_of(candidate)
    if not left or not right:
        return False
    return same_site_host(left, right)


def mentions_host(text: str, host: str) -> bool:
    """Report whether the normalized text contains the host or its `www.` form.

    Literal only, with word boundaries: `rival.ru` is found inside
    `shop.rival.ru` and `https://www.rival.ru/`, never inside `notrival.ru`.
    """
    normalized = normalize_text(text)
    target = normalize_text(host).strip(".").removeprefix("www.")
    if not normalized or not target:
        return False
    return re.search(_HOST_PATTERN.format(re.escape(target)), normalized) is not None


def merge_services(user_services: Sequence[str], site_services: Sequence[str]) -> tuple[str, ...]:
    """Merge user services with the ones found on the site.

    User services come first and keep the entered spelling; a service found on
    the site is appended only when its normalized form is new.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for service in (*user_services, *site_services):
        if not isinstance(service, str):
            continue
        text = service.strip()
        key = normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(text)
    return tuple(merged)


@dataclass(frozen=True)
class SeedResult:
    """One successful key-query SERP.

    ``documents`` holds ``(position, url, title)`` triples in SERP order:
    ``position`` is 1-based, ``url`` is the result URL, and ``title`` is the
    SERP title or an empty string when the response had none.
    """

    query_index: int
    documents: tuple[tuple[int, str, str], ...]


@dataclass(frozen=True)
class Candidate:
    """One domain seen in the key-query SERPs, with its evidence."""

    host: str
    title: str
    occurrences: int
    average_position: float
    seed_indexes: tuple[int, ...]
    recurring: bool


def rank_candidates(seed_results: Sequence[SeedResult], user_host: str) -> tuple[Candidate, ...]:
    """Rank external domains of the key SERPs by occurrences, then position, then host.

    A domain is counted once per successful SERP (its first position in that
    SERP), so ``occurrences`` is the number of SERPs it appeared in and
    ``recurring`` means at least two. The user host and its subdomains, results
    outside the top ten, and non-HTTP(S) URLs are skipped. One-off domains stay
    in the list with ``recurring=False``; with fewer than two successful SERPs
    no domain is recurring.
    """
    results = tuple(seed_results)
    positions: dict[str, list[int]] = {}
    titles: dict[str, str] = {}
    indexes: dict[str, list[int]] = {}

    for result in results:
        first_in_serp: dict[str, tuple[int, str]] = {}
        for document in result.documents:
            position, url, title = document
            if not isinstance(position, int) or not 1 <= position <= TOP_RESULTS:
                continue
            host = result_url_host(url if isinstance(url, str) else "")
            if not host:
                continue
            if user_host and same_site_host(user_host, host):
                continue
            if host not in first_in_serp:
                first_in_serp[host] = (position, title if isinstance(title, str) else "")
        for host, (position, title) in first_in_serp.items():
            positions.setdefault(host, []).append(position)
            indexes.setdefault(host, []).append(result.query_index)
            if title and not titles.get(host):
                titles[host] = title

    candidates = [
        Candidate(
            host=host,
            title=titles.get(host, ""),
            occurrences=len(found),
            average_position=round(sum(found) / len(found), 2),
            seed_indexes=tuple(sorted(indexes[host])),
            recurring=len(found) >= 2 and len(results) >= 2,
        )
        for host, found in positions.items()
    ]
    candidates.sort(key=lambda candidate: (-candidate.occurrences, candidate.average_position, candidate.host))
    return tuple(candidates)


SeoRowOutcome = Literal["found", "absent", "error", "interrupted", "cancelled"]


@dataclass(frozen=True)
class SearchRowValue:
    """One saved Yandex row of a generated query."""

    query_index: int
    status: SeoRowOutcome
    site_position: int | None = None
    site_url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ModelRowValue:
    """One saved model answer for one connection and one generated query."""

    connection_id: str
    query_index: int
    status: SeoRowOutcome
    answer: str | None = None
    name_mentioned: bool | None = None
    host_mentioned: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class CandidateHit:
    """One recurring candidate found in a generated query's top-ten SERP."""

    host: str
    position: int
    url: str | None = None


@dataclass(frozen=True)
class QueryFlags:
    """Server-computed marks of one generated query."""

    mentions_company_name: bool
    mentions_company_host: bool
    mentions_candidate_host: bool
    branded: bool


@dataclass(frozen=True)
class GeneratedQuery:
    """One accepted generated query with its category, service, and flags."""

    text: str
    category: str
    service: str | None
    flags: QueryFlags


def accept_generated_queries(payload: object, services: Sequence[str]) -> tuple[GeneratedQuery, ...]:
    """Validate one generation answer and return at most the fixed query limit.

    ``payload`` may be the raw answer text, a JSON object with a ``queries``
    list, or that list itself. A broken schema, an unknown category, or a query
    outside the Yandex length and word limits is a domain error; duplicate
    queries are dropped by normalized text in model order; entries beyond the
    limit are cut; an unknown or empty service becomes ``None``. Fewer than
    five unique queries is a domain error the orchestrator answers with one
    regeneration attempt.
    """
    known_services = {normalize_text(service): service for service in services if normalize_text(service)}
    accepted: list[GeneratedQuery] = []
    seen: set[str] = set()

    for item in _query_items(payload):
        if not isinstance(item, dict):
            raise ValidationError(INVALID_GENERATED)
        query, category, service = item.get("query"), item.get("category"), item.get("service")
        if not isinstance(query, str) or not query.strip():
            raise ValidationError(INVALID_GENERATED)
        if not isinstance(category, str) or category not in QUERY_CATEGORIES:
            raise ValidationError(INVALID_GENERATED_CATEGORY)
        if service is not None and not isinstance(service, str):
            raise ValidationError(INVALID_GENERATED)
        text = query.strip()
        if len(text) > MAX_QUERY_LENGTH or len(text.split()) > MAX_QUERY_WORDS:
            raise ValidationError(INVALID_GENERATED_LIMITS)
        key = normalize_text(text)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            GeneratedQuery(
                text=text,
                category=category,
                service=known_services.get(normalize_text(service)) if isinstance(service, str) else None,
                flags=QueryFlags(False, False, False, False),
            )
        )
        if len(accepted) >= GENERATED_QUERY_LIMIT:
            break

    if len(accepted) < MIN_GENERATED_QUERIES:
        raise ValidationError(TOO_FEW_GENERATED)
    return tuple(accepted)


def flag_queries(
    queries_without_flags: Sequence[GeneratedQuery],
    company_name: str,
    company_host: str,
    candidate_hosts: Sequence[str],
) -> tuple[GeneratedQuery, ...]:
    """Mark every query by the server instead of trusting the model's own labels.

    The company name is matched with literal whole-phrase rules, the company
    host and each candidate host with word-bounded host matching. A query is
    branded when it names the company by name or by host.
    """
    hosts = tuple(host for host in candidate_hosts if isinstance(host, str) and host.strip())
    flagged: list[GeneratedQuery] = []
    for query in queries_without_flags:
        name_mentioned = bool(company_name) and mentions_phrase(query.text, company_name)
        host_mentioned = bool(company_host) and mentions_host(query.text, company_host)
        candidate_mentioned = any(mentions_host(query.text, host) for host in hosts)
        flagged.append(
            replace(
                query,
                flags=QueryFlags(
                    mentions_company_name=name_mentioned,
                    mentions_company_host=host_mentioned,
                    mentions_candidate_host=candidate_mentioned,
                    branded=name_mentioned or host_mentioned,
                ),
            )
        )
    return tuple(flagged)


def _query_items(payload: object) -> list:
    """Return the raw query list of an answer, fenced JSON included."""
    if isinstance(payload, str):
        items = parse_json_object(payload).get("queries")
    elif isinstance(payload, dict):
        items = payload.get("queries")
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValidationError(INVALID_GENERATED)
    if not isinstance(items, list):
        raise ValidationError(INVALID_GENERATED)
    return items


def _host_of(value: str) -> str:
    """Return the host of a bare name or an HTTP(S) URL, or an empty string."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if "://" in text:
        return result_url_host(text) or ""
    return text


def _is_ip_literal(host: str) -> bool:
    """Report whether a canonical host is an IP address rather than a domain.

    Short forms such as `127.1` and decimal literals are refused as well: every
    all-numeric host is an address to a resolver, never a registrable domain.
    """
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return bool(re.fullmatch(r"[0-9.]+", host))
    return True


def _normalize_seeds(value: object) -> tuple[str, ...]:
    """Keep exactly three distinct non-empty key queries inside the Yandex limits."""
    if not isinstance(value, list) or len(value) != SEED_COUNT:
        raise ValidationError(INVALID_SEEDS)
    seeds: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(INVALID_SEEDS)
        text = item.strip()
        if not text or len(text) > MAX_QUERY_LENGTH or len(text.split()) > MAX_QUERY_WORDS:
            raise ValidationError(INVALID_SEED_LIMITS)
        key = normalize_text(text)
        if key in seen:
            raise ValidationError(INVALID_SEEDS)
        seen.add(key)
        seeds.append(text)
    return tuple(seeds)


def _normalize_services(value: object) -> tuple[str, ...]:
    """Keep 1..20 distinct services of at most 100 characters in entered order."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SERVICES:
        raise ValidationError(INVALID_SERVICES)
    services: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(INVALID_SERVICES)
        text = item.strip()
        if not 1 <= len(text) <= MAX_SERVICE_LENGTH:
            raise ValidationError(INVALID_SERVICES)
        key = normalize_text(text)
        if key in seen:
            raise ValidationError(INVALID_SERVICES)
        seen.add(key)
        services.append(text)
    return tuple(services)


def _normalize_connection_ids(value: object) -> tuple[str, ...]:
    """Keep 1..5 distinct non-empty model connection IDs."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CONNECTIONS:
        raise ValidationError(INVALID_CONNECTIONS)
    ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(INVALID_CONNECTIONS)
        text = item.strip()
        if not text or text in seen:
            raise ValidationError(INVALID_CONNECTIONS)
        seen.add(text)
        ids.append(text)
    return tuple(ids)
