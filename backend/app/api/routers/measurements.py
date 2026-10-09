"""Saved project measurements and paginated evidence."""

from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.deps.dependencies import ContainerDep

router = APIRouter(prefix="/measurements", tags=["measurements"])


@router.get("/{id}")
def get_measurement(id: str, container: ContainerDep) -> dict:
    return container.measurements.get(id)


@router.get("/{id}/rows")
def measurement_rows(
    id: str,
    container: ContainerDep,
    kind: Literal["model", "search"] = "model",
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    return container.measurements.rows_page(id, kind, cursor, limit)


@router.post("/{id}/cancel")
def cancel_measurement(id: str, container: ContainerDep) -> dict:
    return container.measurements.cancel(id)


@router.delete("/{id}", status_code=204)
def delete_measurement(id: str, container: ContainerDep):
    container.measurements.delete(id)
    return Response(status_code=204)
