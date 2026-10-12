"""Strict public schemas for the SEO service-LLM settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr


class SeoSettingsWriteRequest(BaseModel):
    """A partial update; an omitted field is left untouched.

    `extra="forbid"` keeps unknown fields out, and the strict string defaults
    reject `null` and non-string values before the repository is reached.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: StrictStr = ""
    model: StrictStr = ""
    api_key: StrictStr = ""


class SeoSettingsResponse(BaseModel):
    endpoint: str | None
    model: str | None
    has_api_key: bool
    endpoint_source: Literal["ui", "env", "none"]
    model_source: Literal["ui", "env", "none"]
    api_key_source: Literal["ui", "env", "none"]


class SeoSettingsTestResponse(BaseModel):
    ok: bool
    model: str | None = None
    error: str | None = None
