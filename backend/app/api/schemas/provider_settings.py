"""HTTP shapes for the provider settings resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SettingsWriteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    models: list[dict] | None = None


class SettingsModelResponse(BaseModel):
    id: str
    model: str
    name: str


class SettingsProviderResponse(BaseModel):
    id: str
    name: str
    kind: str
    endpoint: str
    configured: bool
    models: list[SettingsModelResponse]
