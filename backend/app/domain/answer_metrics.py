"""Pure answer metrics: citations, brand positions, and the cited sources.

The AI tracker stores one model answer per query and connection and computes
every share on the server from those rows — never from a model-written total.
The vocabulary lives here: how often a connection cited the site, where the
brand is first named inside one answer, and which external domains the models
cited most.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.matching import mentions_host, mentions_phrase, normalize_text
from app.domain.projects import mentions_project_domain
from app.domain.seo_answer import SeoAnswer, normalize_source_url
from app.domain.site_fetch import canonical_host, same_site_host

FINITE_OUTCOMES = frozenset({"found", "absent"})
SOURCE_LIMIT = 20

RowOutcome = Literal["found", "absent", "error", "interrupted", "cancelled"]


@dataclass(frozen=True)
class Metric:
    """One share.

    ``share`` is ``successes / denominator`` rounded to four places, or `None`
    when the denominator is empty; ``average_position`` is the mean of the found
    positions, or `None` when nothing was found or the metric is not positional
    (every AI metric).
    """

    denominator: int
    successes: int
    share: float | None
    average_position: float | None


@dataclass(frozen=True)
class ModelRowValue:
    """One saved model answer for one connection and one query."""

    connection_id: str
    query_index: int
    status: RowOutcome
    answer: str | None = None
    name_mentioned: bool | None = None
    host_mentioned: bool | None = None
    error: str | None = None
    seo_answer: SeoAnswer | None = None


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


def _source_counts(
    models: Sequence[ModelRowValue], host: str, include_subdomains: bool = True
) -> list[dict]:
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


def _citation_metric(
    rows: Iterable[ModelRowValue], connection_id: str, host: str, include_subdomains: bool = True
) -> Metric:
    finite = [
        row
        for row in rows
        if row.connection_id == connection_id
        and row.status in FINITE_OUTCOMES
        and row.seo_answer is not None
        and row.seo_answer.search_status == "completed"
    ]
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


# Public pure helpers shared by fixed-query measurements.
citation_metric = _citation_metric
source_counts = _source_counts


def brand_position_with_aliases(
    rows, connection_id, company_name, host, candidate_hosts, aliases=(), include_subdomains=True
):
    """Exact brand/alias and site-scope positions for project measurements."""
    answered = [
        r
        for r in rows
        if r.connection_id == connection_id and r.status in FINITE_OUTCOMES and _answered(r)
    ]
    counts = {k: 0 for k in ("first", "early", "late", "absent")}
    ahead_total = ahead = 0
    for row in answered:
        paragraphs = _paragraphs(row.answer)
        number = next(
            (
                i
                for i, p in enumerate(paragraphs, 1)
                if any(mentions_phrase(p, n) for n in (company_name, *aliases))
                or mentions_project_domain(
                    p, {"site_url": "https://" + host, "include_subdomains": include_subdomains}
                )
            ),
            None,
        )
        key = "absent" if number is None else "first" if number == 1 else "early" if number <= 3 else "late"
        counts[key] += 1
        rivals = [
            n
            for c in candidate_hosts
            if (n := _first_mention_paragraph(row.answer, "", c)) is not None
        ]
        if rivals:
            ahead_total += 1
            ahead += number is not None and all(number < n for n in rivals)
    return {**{k: _metric(len(answered), n) for k, n in counts.items()}, "ahead": _metric(ahead_total, ahead)}
