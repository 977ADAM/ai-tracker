"""SEO report metrics computed from saved rows only.

The exact aggregate structure, consumed by the frontend in Task 9:

```
{
  "site": {
    "search": {"overall": Metric, "branded": Metric, "unbranded": Metric},
    "ai": {
      "<connection_id>": {
        "name": Metric, "host": Metric, "combined": Metric,
        "position": {"first": Metric, "early": Metric, "late": Metric,
                     "absent": Metric, "ahead": Metric},
        "branded":   {"name": Metric, "host": Metric, "combined": Metric},
        "unbranded": {"name": Metric, "host": Metric, "combined": Metric},
      }
    },
  },
  "competitors": [
    {
      "host": str, "title": str, "occurrences": int,
      "average_position": float, "seed_indexes": tuple[int, ...],
      "search": {"overall": Metric, "branded": Metric, "unbranded": Metric},
      "ai": {"<connection_id>": {"host": Metric}},
    }
  ],
  "categories": {"<category>": {"search": Metric, "ai": {"<connection_id>": Metric}}},
  "services": {"<service or empty>": {"search": Metric, "ai": {"<connection_id>": Metric}}},
  "sources": [{"domain": str, "answers": int, "citations": int}],
  "counts": {
    "queries": int, "search_rows": int, "model_rows": int,
    "search_errors": int, "model_errors": int,
  },
}
```

Rules: a `Metric.share` is a fraction of the denominator (`None` when the
denominator is empty and the UI prints `—`), and `average_position` is `None`
when nothing was found. Only rows with a finite status (`found`, `absent`)
enter a denominator; `error`, `interrupted`, and `cancelled` rows never do and
are never read as an absent mention or an absent site. A Yandex success is
`found` inside the top ten; a model success is a non-empty answer plus the
corresponding flag. Candidate metrics are computed by host: hits come from
`candidate_hits` (query index to top-ten hits) and candidate AI mentions are
re-matched in the saved answer text, never on the SERP title.

`position` is the paragraph heuristic of one connection (first/early/late/absent
for the brand, plus `ahead` against the mentioned candidate hosts); it is
connection-level only and is never duplicated into the branded/unbranded splits.

`sources` ranks the external domains the models cited. Only rows with a
completed web search contribute, the user's own host and its subdomains are
skipped, and the list keeps the top twenty by answers, then citations, then
domain name.

The report is numbers-only: every aggregate here is computed by the server from
the stored rows, and no model-written text is attached to it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.matching import normalize_text
from app.domain.search import TOP_RESULTS
from app.domain.seo import (
    QUERY_CATEGORIES,
    Candidate,
    CandidateHit,
    GeneratedQuery,
    ModelRowValue,
    SearchRowValue,
    SeoInput,
    hosts_match,
    mentions_host,
)
from app.domain.seo_answer import normalize_source_url
from app.domain.site_fetch import canonical_host, same_site_host

FINITE_OUTCOMES = frozenset({"found", "absent"})
ERROR_OUTCOMES = frozenset({"error", "interrupted", "cancelled"})

NAME = "name"
HOST = "host"
COMBINED = "combined"
SOURCE_LIMIT = 20


@dataclass(frozen=True)
class Metric:
    """One report share.

    ``share`` is ``successes / denominator`` rounded to four places, or `None`
    when the denominator is empty; ``average_position`` is the mean of the
    found Yandex positions, or `None` when nothing was found or the metric is
    not positional (every AI metric).
    """

    denominator: int
    successes: int
    share: float | None
    average_position: float | None


def build_report(
    input: SeoInput,
    company_name: str,
    services: Sequence[str],
    candidates: Sequence[Candidate],
    queries: Sequence[GeneratedQuery],
    search_rows: Sequence[SearchRowValue],
    model_rows: Sequence[ModelRowValue],
    *,
    candidate_hits: Mapping[int, Sequence[CandidateHit]] | None = None,
) -> dict[str, object]:
    """Aggregate saved rows into the report payload described in the module docstring.

    ``candidate_hits`` maps a generated query index to the recurring-candidate
    hits found in its SERP; it is the extra input the site rows do not carry,
    and it is keyword-only so the seven documented inputs stay in place.
    """
    query_list = tuple(queries)
    searches = tuple(search_rows)
    models = tuple(model_rows)
    hits = {int(index): tuple(found) for index, found in (candidate_hits or {}).items()}

    known_indexes = set(range(len(query_list)))
    branded_indexes = {index for index, query in enumerate(query_list) if query.flags.branded}
    connections = _connections(input, models)
    candidate_hosts = tuple(candidate.host for candidate in candidates)

    site = {
        "search": {
            "overall": _search_metric(searches),
            "branded": _search_metric(row for row in searches if row.query_index in branded_indexes),
            "unbranded": _search_metric(
                row
                for row in searches
                if row.query_index in known_indexes and row.query_index not in branded_indexes
            ),
        },
        "ai": {
            connection_id: _site_ai_block(
                connection_id,
                models,
                branded_indexes,
                known_indexes,
                input.host,
                company_name,
                candidate_hosts,
            )
            for connection_id in connections
        },
    }

    competitors = [
        _competitor_block(candidate, searches, models, query_list, hits, connections)
        for candidate in candidates
        if candidate.recurring
    ]

    categories: dict[str, object] = {}
    for category in QUERY_CATEGORIES:
        indexes = {index for index, query in enumerate(query_list) if query.category == category}
        categories[category] = {
            "citation": {connection_id: _citation_metric((row for row in models if row.query_index in indexes), connection_id, input.host) for connection_id in connections},
            "search": _search_metric(row for row in searches if row.query_index in indexes),
            "ai": {
                connection_id: _ai_metric(
                    (row for row in models if row.query_index in indexes),
                    connection_id,
                    COMBINED,
                )
                for connection_id in connections
            },
        }

    services_block: dict[str, object] = {}
    for service in _service_keys(services, query_list):
        indexes = {index for index, query in enumerate(query_list) if (query.service or "") == service}
        services_block[service] = {
            "citation": {connection_id: _citation_metric((row for row in models if row.query_index in indexes), connection_id, input.host) for connection_id in connections},
            "search": _search_metric(row for row in searches if row.query_index in indexes),
            "ai": {
                connection_id: _ai_metric(
                    (row for row in models if row.query_index in indexes),
                    connection_id,
                    COMBINED,
                )
                for connection_id in connections
            },
        }

    return {
        "site": site,
        "competitors": competitors,
        "categories": categories,
        "services": services_block,
        "sources": _source_counts(models, input.host),
        "counts": {
            "queries": len(query_list),
            "search_rows": len(searches),
            "model_rows": len(models),
            "search_errors": sum(1 for row in searches if row.status in ERROR_OUTCOMES),
            "model_errors": sum(1 for row in models if row.status in ERROR_OUTCOMES),
        },
    }


def _search_metric(rows: Iterable[SearchRowValue]) -> Metric:
    """Yandex share of finite rows; a success is a top-ten `found` row."""
    finite = [row for row in rows if row.status in FINITE_OUTCOMES]
    positions = [
        row.site_position
        for row in finite
        if row.status == "found" and isinstance(row.site_position, int)
    ]
    return _metric(len(finite), len(positions), positions)


def _candidate_search_metric(
    rows: Iterable[SearchRowValue],
    host: str,
    hits: Mapping[int, Sequence[CandidateHit]],
) -> Metric:
    """Candidate Yandex share over finite rows, using the query's candidate hits."""
    finite = [row for row in rows if row.status in FINITE_OUTCOMES]
    positions = [
        position
        for row in finite
        if (position := _candidate_position(hits.get(row.query_index, ()), host)) is not None
    ]
    return _metric(len(finite), len(positions), positions)


def _candidate_position(hits: Sequence[CandidateHit], host: str) -> int | None:
    """Return the best top-ten position of the candidate host in one SERP."""
    positions = [
        hit.position
        for hit in hits
        if isinstance(hit.position, int)
        and 1 <= hit.position <= TOP_RESULTS
        and hosts_match(host, hit.host)
    ]
    return min(positions) if positions else None


def _site_ai_block(
    connection_id: str,
    models: Sequence[ModelRowValue],
    branded_indexes: set[int],
    known_indexes: set[int],
    host: str,
    company_name: str,
    candidate_hosts: Sequence[str],
) -> dict[str, object]:
    """Name, host, and combined AI shares of one connection plus both splits."""
    rows = [row for row in models if row.connection_id == connection_id]
    branded = [row for row in rows if row.query_index in branded_indexes]
    unbranded = [
        row
        for row in rows
        if row.query_index in known_indexes and row.query_index not in branded_indexes
    ]
    return {
        NAME: _ai_metric(rows, connection_id, NAME),
        HOST: _ai_metric(rows, connection_id, HOST),
        COMBINED: _ai_metric(rows, connection_id, COMBINED),
        "citation": _citation_metric(rows, connection_id, host),
        "position": _brand_position(rows, connection_id, company_name, host, candidate_hosts),
        "branded": _ai_group(branded, connection_id, host),
        "unbranded": _ai_group(unbranded, connection_id, host),
    }


def _ai_group(rows: Sequence[ModelRowValue], connection_id: str, host: str) -> dict[str, Metric]:
    return {
        NAME: _ai_metric(rows, connection_id, NAME),
        HOST: _ai_metric(rows, connection_id, HOST),
        COMBINED: _ai_metric(rows, connection_id, COMBINED),
        "citation": _citation_metric(rows, connection_id, host),
    }


def _ai_metric(rows: Iterable[ModelRowValue], connection_id: str, kind: str) -> Metric:
    """AI share of one connection: answered rows with the corresponding flag."""
    finite = [
        row
        for row in rows
        if row.connection_id == connection_id and row.status in FINITE_OUTCOMES
    ]
    successes = sum(1 for row in finite if _answered(row) and _flagged(row, kind))
    return _metric(len(finite), successes)


def _candidate_ai_metric(rows: Iterable[ModelRowValue], connection_id: str, host: str) -> Metric:
    """Candidate AI share: answered rows that literally mention the candidate host."""
    finite = [
        row
        for row in rows
        if row.connection_id == connection_id and row.status in FINITE_OUTCOMES
    ]
    successes = sum(
        1
        for row in finite
        if _answered(row) and isinstance(row.answer, str) and mentions_host(row.answer, host)
    )
    return _metric(len(finite), successes)


def _competitor_block(
    candidate: Candidate,
    searches: Sequence[SearchRowValue],
    models: Sequence[ModelRowValue],
    queries: Sequence[GeneratedQuery],
    hits: Mapping[int, Sequence[CandidateHit]],
    connections: Sequence[str],
) -> dict[str, object]:
    """One recurring candidate with its Yandex evidence and host-only AI shares."""
    branded_indexes = {
        index for index, query in enumerate(queries) if mentions_host(query.text, candidate.host)
    }
    known_indexes = set(range(len(queries)))
    return {
        "host": candidate.host,
        "title": candidate.title,
        "occurrences": candidate.occurrences,
        "average_position": candidate.average_position,
        "seed_indexes": candidate.seed_indexes,
        "search": {
            "overall": _candidate_search_metric(searches, candidate.host, hits),
            "branded": _candidate_search_metric(
                (row for row in searches if row.query_index in branded_indexes),
                candidate.host,
                hits,
            ),
            "unbranded": _candidate_search_metric(
                (
                    row
                    for row in searches
                    if row.query_index in known_indexes and row.query_index not in branded_indexes
                ),
                candidate.host,
                hits,
            ),
        },
        "ai": {
            connection_id: {"host": _candidate_ai_metric(models, connection_id, candidate.host),
                            "citation": _citation_metric(models, connection_id, candidate.host)}
            for connection_id in connections
        },
    }


def _answered(row: ModelRowValue) -> bool:
    """An empty or missing answer is never a mention."""
    return isinstance(row.answer, str) and bool(row.answer.strip())


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _paragraphs(text: str) -> tuple[str, ...]:
    """Split an answer into its non-empty paragraphs on blank lines."""
    return tuple(part for part in _PARAGRAPH_BREAK.split(text) if part.strip())


def _paragraph_mentions(paragraph: str, company_name: str, host: str) -> bool:
    """Whether one paragraph names the company (folded name or host)."""
    name = normalize_text(company_name)
    if name and name in normalize_text(paragraph):
        return True
    return mentions_host(paragraph, host)


def _first_mention_paragraph(text: str, company_name: str, host: str) -> int | None:
    """The 1-based number of the first paragraph that mentions the company."""
    for number, paragraph in enumerate(_paragraphs(text), 1):
        if _paragraph_mentions(paragraph, company_name, host):
            return number
    return None


def _brand_position(
    rows: Sequence[ModelRowValue],
    connection_id: str,
    company_name: str,
    host: str,
    candidate_hosts: Sequence[str],
) -> dict[str, Metric]:
    """Where the brand is first named in the answered rows of one connection.

    ``first``/``early``/``late``/``absent`` share one denominator: the rows with
    a finite status (`found` or `absent`) and a non-empty answer, so an answered
    row that never names the brand counts as ``absent``. ``ahead`` counts only
    rows that mention at least one candidate host, and a success needs the brand
    strictly earlier than every mentioned candidate, so a mention in the same
    paragraph is not ahead. Both denominators are empty when nothing qualifies,
    and their ``share`` is then `None`.
    """
    answered = [
        row
        for row in rows
        if row.connection_id == connection_id
        and row.status in FINITE_OUTCOMES
        and _answered(row)
    ]
    first = early = late = absent = 0
    ahead_denominator = 0
    ahead_successes = 0
    for row in answered:
        if not isinstance(row.answer, str):  # `_answered` already guarantees this
            continue
        paragraph = _first_mention_paragraph(row.answer, company_name, host)
        if paragraph is None:
            absent += 1
        elif paragraph == 1:
            first += 1
        elif paragraph <= 3:
            early += 1
        else:
            late += 1
        candidate_paragraphs = [
            number
            for candidate_host in candidate_hosts
            if (number := _first_mention_paragraph(row.answer, "", candidate_host)) is not None
        ]
        if candidate_paragraphs:
            ahead_denominator += 1
            if paragraph is not None and all(paragraph < number for number in candidate_paragraphs):
                ahead_successes += 1
    total = len(answered)
    return {
        "first": _metric(total, first),
        "early": _metric(total, early),
        "late": _metric(total, late),
        "absent": _metric(total, absent),
        "ahead": _metric(ahead_denominator, ahead_successes),
    }


def _source_counts(models: Sequence[ModelRowValue], host: str, include_subdomains: bool = True) -> list[dict]:
    """The most cited external domains of the completed web searches.

    ``answers`` counts the rows that cited the domain at least once and
    ``citations`` counts every citation of it; the user's own host and its
    subdomains are skipped, and the top twenty stay.
    """
    citations: dict[str, int] = {}
    answers: dict[str, int] = {}
    for row in models:
        answer = row.seo_answer
        if answer is None or answer.search_status != "completed":
            continue
        cited: list[str] = []
        for citation in answer.citations:
            if normalize_source_url(citation.url) is None:
                continue
            domain = canonical_host(citation.url)
            if domain == host or (include_subdomains and same_site_host(host, domain)):
                continue
            citations[domain] = citations.get(domain, 0) + 1
            if domain not in cited:
                cited.append(domain)
        for domain in cited:
            answers[domain] = answers.get(domain, 0) + 1
    ranked = sorted(citations, key=lambda domain: (-answers[domain], -citations[domain], domain))
    return [
        {"domain": domain, "answers": answers[domain], "citations": citations[domain]}
        for domain in ranked[:SOURCE_LIMIT]
    ]


def _citation_metric(rows: Iterable[ModelRowValue], connection_id: str, host: str, include_subdomains: bool = True) -> Metric:
    finite = [row for row in rows if row.connection_id == connection_id and row.status in FINITE_OUTCOMES
              and row.seo_answer is not None and row.seo_answer.search_status == "completed"]
    positions: list[int] = []
    for row in finite:
        domains: list[str] = []
        for citation in row.seo_answer.citations:
            if normalize_source_url(citation.url) is None:
                continue
            domain = canonical_host(citation.url)
            # Count the target and its subdomains as one site in the ordering.
            domain = host if domain == host or (include_subdomains and same_site_host(host, domain)) else domain
            if domain not in domains:
                domains.append(domain)
        if host in domains:
            positions.append(domains.index(host) + 1)
    return _metric(len(finite), len(positions), positions)


def _flagged(row: ModelRowValue, kind: str) -> bool:
    if kind == NAME:
        return bool(row.name_mentioned)
    if kind == HOST:
        return bool(row.host_mentioned)
    return bool(row.name_mentioned or row.host_mentioned)


def _connections(input: SeoInput, models: Sequence[ModelRowValue]) -> tuple[str, ...]:
    """Selected connections first, then any extra connection seen in the rows."""
    connections: list[str] = []
    seen: set[str] = set()
    for connection_id in (*input.connection_ids, *(row.connection_id for row in models)):
        if isinstance(connection_id, str) and connection_id and connection_id not in seen:
            seen.add(connection_id)
            connections.append(connection_id)
    return tuple(connections)


def _service_keys(services: Sequence[str], queries: Sequence[GeneratedQuery]) -> tuple[str, ...]:
    """Merged services in order, plus an empty key when a query has no service."""
    keys: list[str] = []
    seen: set[str] = set()
    for service in services:
        if not isinstance(service, str):
            continue
        text = service.strip()
        key = normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(text)
    for query in queries:
        if not query.service:
            continue
        key = normalize_text(query.service)
        if key and key not in seen:
            seen.add(key)
            keys.append(query.service)
    if any(query.service is None for query in queries):
        keys.append("")
    return tuple(keys)


def _metric(denominator: int, successes: int, positions: Sequence[int] = ()) -> Metric:
    """Build one metric; an empty denominator or no found position yields `None`."""
    found = tuple(positions)
    share = round(successes / denominator, 4) if denominator > 0 else None
    average = round(sum(found) / len(found), 2) if found else None
    return Metric(
        denominator=denominator,
        successes=successes,
        share=share,
        average_position=average,
    )

# Public pure helpers shared by fixed-query measurements and legacy SEO reports.
brand_position = _brand_position
citation_metric = _citation_metric
source_counts = _source_counts


def brand_position_with_aliases(rows, connection_id, company_name, host, candidate_hosts, aliases=(), include_subdomains=True):
    """Exact brand/alias and site-scope positions for project measurements."""
    from app.domain.matching import mentions_phrase
    from app.domain.projects import mentions_project_domain
    answered = [r for r in rows if r.connection_id == connection_id and r.status in FINITE_OUTCOMES and _answered(r)]
    counts = {k:0 for k in ('first','early','late','absent')}
    ahead_total = ahead = 0
    for row in answered:
        paragraphs = _paragraphs(row.answer)
        number = next((i for i,p in enumerate(paragraphs,1) if any(mentions_phrase(p,n) for n in (company_name,*aliases)) or mentions_project_domain(p, {'site_url':'https://'+host,'include_subdomains':include_subdomains})), None)
        key = 'absent' if number is None else 'first' if number == 1 else 'early' if number <= 3 else 'late'
        counts[key] += 1
        rivals = [n for c in candidate_hosts if (n:=_first_mention_paragraph(row.answer,'',c)) is not None]
        if rivals:
            ahead_total += 1
            ahead += number is not None and all(number<n for n in rivals)
    return {**{k:_metric(len(answered),n) for k,n in counts.items()}, 'ahead':_metric(ahead_total,ahead)}
