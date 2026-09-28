"""Create, inspect, list, cancel, and delete durable SEO analyses.

The router only declares routes and dependencies. Validation, storage, and the
six-stage orchestrator live in `domain/seo.py`, `db/seo.py`, and
`service/seo.py`; nothing here starts a paid call inside the HTTP request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import SeoServiceDep
from app.api.schemas import ErrorResponse
from app.api.schemas.seo import (
    SeoAnalysisCreatedResponse,
    SeoAnalysisRequest,
    SeoHistoryPageResponse,
    SeoRowsResponse,
    SeoSnapshotResponse,
)

router = APIRouter(prefix="/seo/analyses", tags=["seo"])
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
    409: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
}


@router.post("", status_code=202, response_model=SeoAnalysisCreatedResponse, responses=ERROR_RESPONSES)
async def create_analysis(seo: SeoServiceDep, payload: SeoAnalysisRequest) -> dict:
    """Create the durable analysis and answer at once; the six stages run in the background."""
    return await seo.start(payload.model_dump())


@router.get("", response_model=SeoHistoryPageResponse, responses=ERROR_RESPONSES)
def list_analyses(seo: SeoServiceDep, cursor: str | None = None) -> dict:
    return seo.list_page(cursor)


@router.get("/{id}", response_model=SeoSnapshotResponse, responses=ERROR_RESPONSES)
def get_analysis(seo: SeoServiceDep, id: str) -> dict:
    return seo.snapshot(id)


@router.get("/{id}/rows", response_model=SeoRowsResponse, responses=ERROR_RESPONSES)
def get_analysis_rows(
    seo: SeoServiceDep, id: str, kind: str, cursor: str | None = None,
) -> dict:
    """Serve the paginated detail; model answers are returned only here."""
    return seo.rows_page(id, kind, cursor)


@router.post("/{id}/cancel", response_model=SeoSnapshotResponse, responses=ERROR_RESPONSES)
async def cancel_analysis(seo: SeoServiceDep, id: str) -> dict:
    """Stop new submissions and polls of one active analysis; the finished rows stay."""
    return seo.cancel(id)


@router.delete("/{id}", status_code=204, responses=ERROR_RESPONSES)
def delete_analysis(seo: SeoServiceDep, id: str) -> Response:
    """Delete a terminal analysis; an active one is a conflict."""
    seo.delete(id)
    return Response(status_code=204)
