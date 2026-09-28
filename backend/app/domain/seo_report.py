"""SEO report metrics computed from saved rows only.

The exact aggregate structure, consumed by the frontend in Task 9:

```
{
  "site": {
    "search": {"overall": Metric, "branded": Metric, "unbranded": Metric},
    "ai": {
      "<connection_id>": {
        "name": Metric, "host": Metric, "combined": Metric,
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

`report_payload` wraps that computed mapping for an agentic run: it copies
every aggregate unchanged and adds the optional model `conclusions` block, so
the report agent can never move a number.
"""

from __future__ import annotations

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

FINITE_OUTCOMES = frozenset({"found", "absent"})
ERROR_OUTCOMES = frozenset({"error", "interrupted", "cancelled"})

NAME = "name"
HOST = "host"
COMBINED = "combined"


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
            connection_id: _site_ai_block(connection_id, models, branded_indexes, known_indexes)
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
        "counts": {
            "queries": len(query_list),
            "search_rows": len(searches),
            "model_rows": len(models),
            "search_errors": sum(1 for row in searches if row.status in ERROR_OUTCOMES),
            "model_errors": sum(1 for row in models if row.status in ERROR_OUTCOMES),
        },
    }


def report_payload(
    metrics: Mapping[str, object],
    *,
    conclusions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Copy the computed metrics and attach the optional conclusions block.

    Every aggregate key is copied unchanged, one level deep: this function
    never reads or rewrites a metric, so a missing, empty, or nonsense
    conclusions block cannot change a number. The block itself is kept as a
    plain `dict` only when it is a non-empty mapping; otherwise it is `None`
    and the report shows no model text.
    """
    payload: dict[str, object] = dict(metrics)
    payload["conclusions"] = _conclusions_block(conclusions)
    return payload


def _conclusions_block(conclusions: object) -> dict[str, object] | None:
    """Return the model conclusions as a plain dict, or `None` when unusable."""
    if not isinstance(conclusions, Mapping) or not conclusions:
        return None
    return {key: value for key, value in conclusions.items()}


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
        "branded": _ai_group(branded, connection_id),
        "unbranded": _ai_group(unbranded, connection_id),
    }


def _ai_group(rows: Sequence[ModelRowValue], connection_id: str) -> dict[str, Metric]:
    return {
        NAME: _ai_metric(rows, connection_id, NAME),
        HOST: _ai_metric(rows, connection_id, HOST),
        COMBINED: _ai_metric(rows, connection_id, COMBINED),
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
            connection_id: {"host": _candidate_ai_metric(models, connection_id, candidate.host)}
            for connection_id in connections
        },
    }


def _answered(row: ModelRowValue) -> bool:
    """An empty or missing answer is never a mention."""
    return isinstance(row.answer, str) and bool(row.answer.strip())


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
