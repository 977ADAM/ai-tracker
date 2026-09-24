"""Dedicated HTTP routes for the model settings modal."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ProviderSettingsServiceDep
from app.api.schemas.provider_settings import (
    ConfigurationFileResponse,
    SettingsProviderResponse,
    SettingsWriteRequest,
)
from app.api.schemas.providers import DeletedResponse

router = APIRouter(tags=["provider settings"])


@router.get("/providers/settings", response_model=list[SettingsProviderResponse])
def list_settings_providers(settings: ProviderSettingsServiceDep) -> list[dict[str, Any]]:
    return settings.list_public()


@router.get("/providers/settings/file", response_model=ConfigurationFileResponse)
def read_configuration_file(settings: ProviderSettingsServiceDep) -> dict[str, Any]:
    return settings.configuration_file()


@router.post("/providers/settings", response_model=SettingsProviderResponse)
def create_settings_provider(settings: ProviderSettingsServiceDep, payload: SettingsWriteRequest) -> dict[str, Any]:
    return settings.save(payload.model_dump(exclude_unset=True))


@router.put("/providers/settings/{group_id}", response_model=SettingsProviderResponse)
def update_settings_provider(group_id: str, settings: ProviderSettingsServiceDep, payload: SettingsWriteRequest) -> dict[str, Any]:
    return settings.save(payload.model_dump(exclude_unset=True), group_id)


@router.delete("/providers/settings/{group_id}", response_model=DeletedResponse)
def delete_settings_provider(group_id: str, settings: ProviderSettingsServiceDep) -> dict[str, bool]:
    settings.delete(group_id)
    return {"deleted": True}
