"""Connection settings endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path

from app.api.deps import ConnectionServiceDep
from app.api.schemas import (
    DeletedResponse,
    ErrorResponse,
    ProviderResponse,
    ProviderWriteRequest,
)

router = APIRouter(tags=["providers"])

BAD_REQUEST = {"model": ErrorResponse, "description": "Некорректные настройки подключения"}
UNAVAILABLE = {"model": ErrorResponse, "description": "Локальное хранилище настроек недоступно"}

ConnectionId = Annotated[str, Path(description="Идентификатор подключения")]


@router.get(
    "/providers",
    response_model=list[ProviderResponse],
    summary="Список подключений",
    responses={503: UNAVAILABLE},
)
def list_providers(connections: ConnectionServiceDep) -> list[dict[str, Any]]:
    """List every saved connection. A key is never part of the response."""
    return connections.list_public()


@router.post(
    "/providers",
    response_model=ProviderResponse,
    summary="Создать или настроить подключение",
    responses={400: BAD_REQUEST, 503: UNAVAILABLE},
)
def add_provider(
    connections: ConnectionServiceDep,
    payload: ProviderWriteRequest,
) -> dict[str, Any]:
    """Create a connection, or set the key and scope of a built-in one."""
    return connections.save(payload.model_dump(exclude_unset=True))


@router.put(
    "/providers/{connection_id}",
    response_model=ProviderResponse,
    summary="Изменить подключение",
    responses={400: BAD_REQUEST, 503: UNAVAILABLE},
)
def update_provider(
    connection_id: ConnectionId,
    connections: ConnectionServiceDep,
    payload: ProviderWriteRequest,
) -> dict[str, Any]:
    """Edit a connection. A blank key keeps the saved one."""
    return connections.save(payload.model_dump(exclude_unset=True), connection_id)


@router.delete(
    "/providers/{connection_id}",
    response_model=DeletedResponse,
    summary="Удалить подключение",
    responses={400: BAD_REQUEST, 503: UNAVAILABLE},
)
def remove_provider(connection_id: ConnectionId, connections: ConnectionServiceDep) -> dict[str, bool]:
    """Delete a connection and its key. A built-in template is reset, not removed."""
    connections.delete(connection_id)
    return {"deleted": True}
