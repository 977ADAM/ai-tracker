"""Pure rules for a combined model and Yandex run."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationError
from app.domain.requests import normalize_check_request, normalize_provider_ids
from app.domain.search import normalize_search_request


@dataclass(frozen=True)
class RunInput:
    project_id: str
    brand: str
    domain: str
    prompts: tuple[str, ...]
    provider_ids: tuple[str, ...]
    regions: tuple[int, ...]
    search_host: str | None
    region_engines: tuple[str, ...] = ()


def normalize_run_request(payload: object) -> RunInput:
    """Apply the selected branches' existing limits before creating paid work."""
    if not isinstance(payload, dict):
        raise ValidationError("Некорректный запрос")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValidationError("Выберите проект")
    ids, regions = payload.get("provider_ids", []), payload.get("regions", [])
    if not isinstance(ids, list) or not isinstance(regions, list) or not (ids or regions):
        raise ValidationError("Выберите модель или регион")
    check = normalize_check_request(payload) if ids else None
    search = normalize_search_request(payload) if regions else None
    return RunInput(
        project_id=project_id.strip(),
        brand=check.brand if check else "",
        domain=search.domain if search else check.domain,
        prompts=search.prompts if search else check.prompts,
        provider_ids=tuple(normalize_provider_ids(payload)) if ids else (),
        regions=search.regions if search else (),
        search_host=search.host if search else None,
        region_engines=search.engines if search else (),
    )


_STATUS_LABELS = {
    "submitting": "Выполняется",
    "waiting": "Выполняется",
    "pending": "Выполняется",
    "mentioned": "Готово",
    "absent": "Готово",
    "found": "Готово",
    "error": "Ошибка",
    "interrupted": "Прервано",
}


def summary_rows(
    models: list[dict],
    search: list[dict],
    *,
    provider_ids: tuple[str, ...],
    regions: tuple[int, ...],
) -> list[dict[str, str]]:
    """Project every stored row to the table and CSV's shared nine fields."""
    output: list[dict[str, str]] = []
    region_order = {region: index for index, region in enumerate(regions)}
    provider_order = {provider: index for index, provider in enumerate(provider_ids)}

    for row in sorted(search, key=lambda item: (region_order[item["region_id"]], item["prompt_index"])):
        status = row["status"]
        output.append({
            "prompt": row["prompt"],
            "source": "Яндекс" if row.get("engine", "yandex") == "yandex" else str(row["engine"]),
            "language": "ru",
            "region": row["region_name"],
            "ai_answer": "—",
            "site_found": "Да" if status == "found" else "Нет" if status == "absent" else "—",
            "position": str(row["position"]) if status == "found" and row["position"] is not None else "—",
            "brand_found": "—",
            "status": _STATUS_LABELS[status],
        })

    for row in sorted(models, key=lambda item: (provider_order[item["provider_id"]], item["prompt_index"])):
        status = row["status"]
        output.append({
            "prompt": row["prompt"],
            "source": row["provider_name"],
            "language": "",
            "region": "—",
            "ai_answer": "Да" if status in ("mentioned", "absent") else "—",
            "site_found": "—",
            "position": "—",
            "brand_found": "Да" if status == "mentioned" else "Нет" if status == "absent" else "—",
            "status": _STATUS_LABELS[status],
        })
    return output
