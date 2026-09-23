"""Connection settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.api.deps import ConnectionServiceDep

router = APIRouter(tags=["providers"])


@router.get("/providers")
def list_providers(connections: ConnectionServiceDep) -> list[dict[str, Any]]:
    """List every saved connection. A key is never part of the response."""
    return connections.list_public()


@router.post("/providers")
def add_provider(
    connections: ConnectionServiceDep,
    payload: object = Body(...),
) -> dict[str, Any]:
    """Create an OpenAI-compatible connection, or configure a built-in one."""
    return connections.save(payload)


@router.put("/providers/{connection_id}")
def update_provider(
    connection_id: str,
    connections: ConnectionServiceDep,
    payload: object = Body(...),
) -> dict[str, Any]:
    """Edit a connection. A blank key keeps the saved one."""
    return connections.save(payload, connection_id)


@router.delete("/providers/{connection_id}")
def remove_provider(connection_id: str, connections: ConnectionServiceDep) -> dict[str, bool]:
    """Delete a connection and its key."""
    connections.delete(connection_id)
    return {"deleted": True}
