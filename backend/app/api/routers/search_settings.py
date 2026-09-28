"""Safe public resource for Yandex search settings."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SearchSettingsServiceDep
from app.api.schemas.search_settings import (
    SearchSettingsResponse,
    SearchSettingsWriteRequest,
)

router = APIRouter(tags=["search settings"])


@router.get("/search/settings", response_model=SearchSettingsResponse)
def read_search_settings(settings: SearchSettingsServiceDep) -> dict[str, object]:
    return settings.public()


@router.put("/search/settings", response_model=SearchSettingsResponse)
def update_search_settings(
    settings: SearchSettingsServiceDep, payload: SearchSettingsWriteRequest,
) -> dict[str, object]:
    return settings.update(payload.model_dump(exclude_unset=True))


@router.delete("/search/settings/credentials", response_model=SearchSettingsResponse)
def reset_search_credentials(settings: SearchSettingsServiceDep) -> dict[str, object]:
    return settings.reset_credentials()
