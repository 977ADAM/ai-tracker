from fastapi import APIRouter, HTTPException
from ai_tracker.connections import ConnectionError, ConnectionStore, KeyringSecrets

router = APIRouter()

@router.get("/api/providers")
def list_providers(active_store) -> list[dict]:
    try:
        return active_store.list_connections()
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc