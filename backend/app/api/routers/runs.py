"""Create, inspect, list, delete, and export durable runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import RunServiceDep
from app.api.schemas import ErrorResponse
from app.api.schemas.runs import (
    RunCreatedResponse,
    RunHistoryPage,
    RunRequest,
    RunSnapshotResponse,
)
from app.service.run_export import render_run_csv

router = APIRouter(prefix="/runs", tags=["runs"])
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
    409: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
}


@router.post("", status_code=202, response_model=RunCreatedResponse, responses=ERROR_RESPONSES)
async def create_run(runs: RunServiceDep, payload: RunRequest) -> dict:
    return await runs.start(payload.model_dump())


@router.get("", response_model=RunHistoryPage, responses=ERROR_RESPONSES)
def list_runs(runs: RunServiceDep, cursor: str | None = None, project_id: str | None = None) -> dict:
    return runs.list_page(cursor, project_id=project_id)


@router.get("/{run_id}", response_model=RunSnapshotResponse, responses=ERROR_RESPONSES)
def get_run(runs: RunServiceDep, run_id: str) -> dict:
    return runs.snapshot(run_id)


@router.delete("/{run_id}", status_code=204, responses=ERROR_RESPONSES)
def delete_run(runs: RunServiceDep, run_id: str) -> Response:
    runs.delete(run_id)
    return Response(status_code=204)


@router.get("/{run_id}/export.csv", responses=ERROR_RESPONSES)
def export_run(runs: RunServiceDep, run_id: str) -> Response:
    snapshot = runs.snapshot(run_id)
    data = render_run_csv(snapshot)
    date = snapshot["created_at"][:10]
    return Response(
        data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ai-serp-results-{date}.csv"'},
    )
