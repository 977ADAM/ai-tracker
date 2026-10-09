"""Server-only aggregates from saved outcomes, never from model-written totals."""

from dataclasses import asdict

from app.domain.matching import mentions_phrase
from app.domain.projects import comparison_key, project_host_matches
from app.domain.search import SearchDocument, first_matching_result, result_url_host
from app.domain.seo import ModelRowValue
from app.domain.seo_answer import answer_from_dict
from app.domain.seo_report import (
    brand_position_with_aliases,
    citation_metric,
    source_counts,
)
from app.domain.site_fetch import canonical_host


def _metric(rows, brand, host, aliases=()):
    answered = [r for r in rows if r["status"] == "success"]
    n = len(answered)

    def matched(row):
        return any(
            mentions_phrase(row.get("answer") or "", name) for name in (brand, *aliases)
        )

    mentions = sum(matched(r) for r in answered)
    sentiment = {k: 0 for k in ("positive", "neutral", "negative", "unknown")}
    for r in answered:
        if matched(r):
            sentiment[(r.get("sentiment") or {}).get("label", "unknown")] += 1
    return {
        "successful": n,
        "mentioned": mentions,
        "visibility": round(mentions / n, 4) if n else None,
        "sentiment": sentiment,
    }


def build_measurement_report(snapshot, model_rows, search_rows):
    p = snapshot["project"]
    host = canonical_host(p["site_url"])
    planned = len(p["queries"]) * len(snapshot["connections"])
    result = {
        **_metric(model_rows, p["brand"], host, p.get("brand_aliases", [])),
        "planned": planned,
    }
    successful = [r for r in model_rows if r["status"] == "success"]
    values = [
        ModelRowValue(
            r["connection_id"],
            r["query_index"],
            "found" if r.get("brand_mentioned") else "absent",
            r.get("answer"),
            r.get("brand_mentioned"),
            r.get("domain_mentioned"),
            seo_answer=answer_from_dict(r["evidence"]) if r.get("evidence") else None,
        )
        for r in successful
    ]
    result["models"] = []
    for c in snapshot["connections"]:
        rows = [r for r in model_rows if r["connection_id"] == c["connection_id"]]
        metric = _metric(rows, p["brand"], host, p.get("brand_aliases", []))
        result["models"].append(
            {
                **metric,
                "connection_id": c["connection_id"],
                "name": c["name"],
                "planned": len(p["queries"]),
                "position": {
                    k: asdict(v)
                    for k, v in brand_position_with_aliases(
                        values,
                        c["connection_id"],
                        p["brand"],
                        host,
                        [
                            (
                                canonical_host(r["site_url"])
                                if r["site_url"]
                                else r["brand"]
                            )
                            for r in p["competitors"]
                        ],
                        p.get("brand_aliases", []),
                        p.get("include_subdomains", True),
                    ).items()
                },
                "citation": asdict(
                    citation_metric(
                        values,
                        c["connection_id"],
                        host,
                        p.get("include_subdomains", True),
                    )
                ),
            }
        )
    result["queries"] = [
        {
            "text": q["text"],
            "category": q.get("category"),
            "group": q.get("group"),
            **_metric(
                [r for r in model_rows if r["query_index"] == i],
                p["brand"],
                host,
                p.get("brand_aliases", []),
            ),
        }
        for i, q in enumerate(p["queries"])
    ]
    groups = {}
    for i, q in enumerate(p["queries"]):
        groups.setdefault(q.get("group") or "Без группы", []).append(i)
    result["groups"] = [
        {
            "name": name,
            **_metric(
                [r for r in model_rows if r["query_index"] in indexes],
                p["brand"],
                host,
                p.get("brand_aliases", []),
            ),
        }
        for name, indexes in groups.items()
    ]
    result["sources"] = source_counts(values, host, p.get("include_subdomains", True))
    result["competitors"] = [
        {
            "brand": c["brand"],
            "site_url": c["site_url"],
            **_metric(
                model_rows,
                c["brand"],
                canonical_host(c["site_url"]) if c["site_url"] else "",
            ),
        }
        for c in p["competitors"]
    ]
    # Competitor sentiment is not classified: only its visibility is available.
    for c in result["competitors"]:
        c.pop("sentiment")
    result["model_errors"] = sum(
        r["status"] in ("error", "cancelled", "interrupted") for r in model_rows
    )
    result["search_errors"] = sum(
        r["status"] in ("error", "cancelled", "interrupted") for r in search_rows
    )
    terminal = ("success", "error", "cancelled", "interrupted")
    result["progress"] = {
        "model_done": sum(r["status"] in terminal for r in model_rows),
        "model_total": planned,
        "sentiment_done": sum(
            r.get("sentiment_status") in ("completed", "unknown") for r in model_rows
        ),
        "sentiment_total": result["mentioned"],
        "search_done": sum(r["status"] in terminal for r in search_rows),
        "search_total": len(search_rows),
    }
    result["search"] = []
    if p["yandex_enabled"]:
        good = [r for r in search_rows if r["status"] == "success"]
        for site in [
            {"brand": p["brand"], "site_url": p["site_url"]},
            *p["competitors"],
        ]:
            if not site["site_url"]:
                continue
            positions = []
            for r in good:
                match = first_matching_result(
                    canonical_host(site["site_url"]),
                    tuple(SearchDocument(**d) for d in r["documents"]),
                )
                if site["site_url"] == p["site_url"] and not p.get(
                    "include_subdomains", True
                ):
                    match = next(
                        (
                            (index, doc["url"])
                            for index, doc in enumerate(r["documents"][:10], 1)
                            if result_url_host(doc["url"])
                            and project_host_matches(p, doc["url"])
                        ),
                        None,
                    )
                if match:
                    positions.append(match[0])
            result["search"].append(
                {
                    **site,
                    "successful": len(good),
                    "found": len(positions),
                    "visibility": len(positions) / len(good) if good else None,
                    "average_position": sum(positions) / len(positions)
                    if positions
                    else None,
                }
            )
    return result


def compare_measurements(current, previous):
    result = {
        "visibility_delta": None,
        "mentioned_delta": None,
        "sentiment_delta": None,
        "reason": None,
    }
    if previous is None:
        result["reason"] = "Первый замер в этой серии настроек"
        return result
    if comparison_key(current["snapshot"]) != comparison_key(previous["snapshot"]):
        result["reason"] = "Настройки изменились: новая серия замеров"
        return result
    a, b = current["aggregates"], previous["aggregates"]
    if (
        current["status"] != "completed"
        or previous["status"] != "completed"
        or a["successful"] != a["planned"]
        or b["successful"] != b["planned"]
    ):
        result["reason"] = "Для сравнения нужно полное покрытие моделей"
        return result
    result["visibility_delta"] = round((a["visibility"] - b["visibility"]) * 100, 2)
    result["mentioned_delta"] = a["mentioned"] - b["mentioned"]
    if not a["sentiment"]["unknown"] and not b["sentiment"]["unknown"]:
        result["sentiment_delta"] = {
            k: a["sentiment"][k] - b["sentiment"][k]
            for k in ("positive", "neutral", "negative")
        }
    else:
        result["reason"] = "Тональность части упоминаний не определена"
    return result
