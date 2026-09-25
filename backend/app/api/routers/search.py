"""Deferred Yandex search endpoints.

The router only declares routes and dependencies: credentials, batching, polling,
and host matching live in `service/search.py`, `integrations/yandex_search.py`,
and `domain/search.py`. `/search/regions` is declared before the dynamic
`/search/{job_id}` so a catalog request is never read as a job ID.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import SearchServiceDep
from app.api.schemas import (
    ErrorResponse,
    SearchCreatedResponse,
    SearchRegionResponse,
    SearchRequest,
    SearchSnapshotResponse,
)
from app.domain.search import REGIONS

router = APIRouter(tags=["search"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Некорректный запрос или не заданы ключи Яндекса"},
    404: {"model": ErrorResponse, "description": "Задача поиска не найдена или больше не хранится"},
}


@router.get(
    "/search/regions",
    response_model=list[SearchRegionResponse],
    summary="Справочник регионов Яндекса",
)
def list_regions() -> list[dict[str, Any]]:
    """Return the documented region IDs the form offers."""
    return [{"id": region_id, "name": name} for region_id, name in REGIONS]


@router.post(
    "/search",
    response_model=SearchCreatedResponse,
    status_code=202,
    summary="Запустить поиск сайта в Яндексе",
    responses=ERROR_RESPONSES,
)
async def start_search(search: SearchServiceDep, payload: SearchRequest) -> dict[str, Any]:
    """Create an in-memory job and return at once; Yandex answers minutes or hours later."""
    return await search.start(payload.model_dump())


@router.get(
    "/search/{job_id}",
    response_model=SearchSnapshotResponse,
    summary="Состояние задачи поиска",
    responses=ERROR_RESPONSES,
)
def search_status(search: SearchServiceDep, job_id: str) -> dict[str, Any]:
    """Return the current snapshot of one job."""
    return search.snapshot(job_id)
