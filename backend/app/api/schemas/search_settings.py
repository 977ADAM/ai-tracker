"""Strict public search settings request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr


class SearchSettingsWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = True
    api_key: StrictStr = ""
    folder_id: StrictStr = ""


class YandexSettingsResponse(BaseModel):
    enabled: bool
    folder_id: str | None
    has_api_key: bool
    api_key_source: Literal["ui", "env", "none"]
    folder_id_source: Literal["ui", "env", "none"]


class SearchSettingsResponse(BaseModel):
    yandex: YandexSettingsResponse
