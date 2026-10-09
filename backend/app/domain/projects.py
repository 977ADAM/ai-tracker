"""Validated project settings and order-independent measurement identity."""

import hashlib
import json
from copy import deepcopy

from app.core.errors import ValidationError
from app.domain.matching import normalize_text
from app.domain.search import KNOWN_REGION_IDS
from app.domain.seo import QUERY_CATEGORIES, url_problem
from app.domain.seo_answer import normalize_source_url


def _text(value, label, limit=100):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValidationError(f"{label}: укажите от 1 до {limit} символов")
    return value.strip()


def _url(value):
    if isinstance(value, str) and value.strip() and "://" not in value:
        value = "https://" + value.strip()
    if url_problem(value) or normalize_source_url(value) is None:
        raise ValidationError("Укажите публичный адрес сайта http(s) с доменным именем")
    return value.strip()


def normalize_project(payload: object) -> dict:
    fields = {
        "name",
        "brand",
        "brand_description",
        "brand_aliases",
        "site_url",
        "include_subdomains",
        "competitors",
        "queries",
        "connection_ids",
        "yandex_enabled",
        "yandex_region",
    }
    if not isinstance(payload, dict) or set(payload) - fields:
        raise ValidationError("Некорректные настройки проекта")
    description = payload.get("brand_description", "")
    if not isinstance(description, str) or len(description.strip()) > 500:
        raise ValidationError("Описание бренда должно содержать не более 500 символов")
    aliases = payload.get("brand_aliases", [])
    if not isinstance(aliases, list) or len(aliases) > 20:
        raise ValidationError("Добавьте не более 20 вариантов названия")
    names = []
    for alias in aliases:
        name = _text(alias, "Вариант названия")
        if normalize_text(name) not in {
            normalize_text(a) for a in names
        } and normalize_text(name) != normalize_text(payload.get("brand", "")):
            names.append(name)
    queries = payload.get("queries", [])
    if not isinstance(queries, list) or not 0 <= len(queries) <= 20:
        raise ValidationError("Добавьте не более 20 запросов")
    normalized = []
    seen = set()
    for q in queries:
        if not isinstance(q, dict) or set(q) - {"text", "category", "group"}:
            raise ValidationError("Некорректный запрос")
        text = _text(q.get("text"), "Запрос", 400)
        category = q.get("category")
        if len(text.split()) > 40 or normalize_text(text) in seen:
            raise ValidationError(
                "Запросы должны различаться и содержать не более 40 слов"
            )
        if category is not None and category not in QUERY_CATEGORIES:
            raise ValidationError("Неизвестная категория запроса")
        group = q.get("group")
        if group is not None:
            if not isinstance(group, str) or len(group.strip()) > 100:
                raise ValidationError(
                    "Название группы должно содержать не более 100 символов"
                )
            group = group.strip() or None
        seen.add(normalize_text(text))
        normalized.append({"text": text, "category": category, "group": group})
    ids = payload.get("connection_ids", [])
    if (
        not isinstance(ids, list)
        or not 0 <= len(ids) <= 5
        or any(not isinstance(i, str) or not i or len(i) > 100 for i in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValidationError("Выберите от 1 до 5 разных моделей")
    competitors = payload.get("competitors", [])
    if not isinstance(competitors, list) or len(competitors) > 10:
        raise ValidationError("Добавьте не более 10 конкурентов")
    rivals = []
    for c in competitors:
        if not isinstance(c, dict) or set(c) != {"brand", "site_url"}:
            raise ValidationError("Укажите бренд и сайт конкурента")
        rival = {
            "brand": _text(c.get("brand") or c.get("site_url"), "Бренд конкурента"),
            "site_url": _url(c.get("site_url")) if c.get("site_url") else "",
        }
        if rival in rivals:
            raise ValidationError("Конкуренты не должны повторяться")
        rivals.append(rival)
    subdomains = payload.get("include_subdomains", True)
    if type(subdomains) is not bool:
        raise ValidationError("Некорректный выбор поддоменов")
    enabled = payload.get("yandex_enabled", False)
    region = payload.get("yandex_region", 213)
    if (
        type(enabled) is not bool
        or type(region) is not int
        or region not in KNOWN_REGION_IDS
    ):
        raise ValidationError("Некорректные настройки Яндекса")
    return {
        "name": _text(payload.get("name") or payload.get("brand"), "Название проекта"),
        "brand": _text(payload.get("brand"), "Бренд"),
        "site_url": _url(payload.get("site_url")),
        "include_subdomains": subdomains,
        "brand_description": description.strip(),
        "brand_aliases": names,
        "competitors": rivals,
        "queries": normalized,
        "connection_ids": ids,
        "yandex_enabled": enabled,
        "yandex_region": region,
    }


def comparison_key(snapshot: dict) -> str:
    from app.domain.site_fetch import canonical_host

    value = deepcopy(snapshot)
    p = value["project"]
    p.pop("name", None)
    p.pop("connection_ids", None)
    p["brand"] = normalize_text(p["brand"])
    p["brand_description"] = normalize_text(p.get("brand_description", ""))
    p["brand_aliases"] = sorted(normalize_text(a) for a in p.get("brand_aliases", []))
    p["site_url"] = canonical_host(p["site_url"])
    p["include_subdomains"] = p.get("include_subdomains", True)
    p["queries"] = sorted(
        (
            {
                "text": normalize_text(q["text"]),
                "category": q.get("category"),
                "group": normalize_text(q.get("group") or "") or None,
            }
            for q in p["queries"]
        ),
        key=lambda q: (q["text"], q["category"] or ""),
    )
    p["competitors"] = sorted(
        (
            {
                "brand": normalize_text(c["brand"]),
                "site_url": canonical_host(c["site_url"]) if c["site_url"] else "",
            }
            for c in p["competitors"]
        ),
        key=lambda c: (c["brand"], c["site_url"]),
    )
    if not p.get("yandex_enabled"):
        p.pop("yandex_region", None)
        value["yandex"] = None
    connections = []
    for c in value["connections"]:
        connections.append(
            {k: v for k, v in c.items() if k not in ("connection_id", "name")}
        )
    value["connections"] = sorted(
        connections, key=lambda c: json.dumps(c, sort_keys=True)
    )
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def mentions_project_brand(answer: str, project: dict) -> bool:
    from app.domain.matching import mentions_phrase

    return any(
        mentions_phrase(answer, name)
        for name in (project["brand"], *project.get("brand_aliases", []))
    )


def project_host_matches(project: dict, other: str) -> bool:
    from app.domain.site_fetch import canonical_host, same_site_host

    target = canonical_host(project["site_url"])
    host = canonical_host(other)
    return (
        same_site_host(target, host)
        if project.get("include_subdomains", True)
        else target == host
    )


def mentions_project_domain(text: str, project: dict) -> bool:
    import re

    from app.domain.seo import mentions_host
    from app.domain.site_fetch import canonical_host

    host = canonical_host(project["site_url"])
    if project.get("include_subdomains", True):
        return mentions_host(text, host)
    return (
        re.search(
            r"(?<![\w.-])(?:www\.)?" + re.escape(host) + r"(?![\w-]|\.[\w-])",
            normalize_text(text),
        )
        is not None
    )
