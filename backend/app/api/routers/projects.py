"""Projects and their repeatable measurement collection."""

from fastapi import APIRouter, Query, Response

from app.api.deps.dependencies import ContainerDep
from app.api.schemas.projects import ProjectRequest, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(
    container: ContainerDep,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return container.projects.list_page(cursor, limit)


@router.post("", status_code=201, response_model=ProjectResponse)
def create_project(payload: ProjectRequest, container: ContainerDep) -> dict:
    return container.projects.create(payload.model_dump())


@router.get("/{id}", response_model=ProjectResponse)
def get_project(id: str, container: ContainerDep) -> dict:
    return container.projects.get(id)


@router.put("/{id}", response_model=ProjectResponse)
def update_project(id: str, payload: ProjectRequest, container: ContainerDep) -> dict:
    return container.projects.update(id, payload.model_dump())


@router.delete("/{id}", status_code=204)
def delete_project(id: str, container: ContainerDep):
    container.projects.delete(id)
    return Response(status_code=204)


@router.get("/{id}/measurements")
def measurement_history(
    id: str,
    container: ContainerDep,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return container.measurements.list_page(id, cursor, limit)


@router.post("/{id}/measurements", status_code=202)
async def start_measurement(id: str, container: ContainerDep) -> dict:
    return await container.measurements.start(id)


from typing import Literal

from pydantic import BaseModel, ConfigDict


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["description", "queries", "competitors"]


@router.post("/{id}/generate")
async def generate_proposal(
    id: str, payload: GenerationRequest, container: ContainerDep
) -> dict:
    try:
        return await container.project_generation.generate(id, payload.kind)
    except TimeoutError:
        from app.core.errors import ProviderError

        raise ProviderError(
            "Генерация превысила 120 секунд. Можно заполнить поля вручную"
        ) from None
