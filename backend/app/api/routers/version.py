"""The installed application version."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.version import application_version

router = APIRouter(tags=["version"])


class VersionResponse(BaseModel):
    """The version from the backend project file."""

    version: str


@router.get("/version", response_model=VersionResponse)
def read_version() -> VersionResponse:
    return VersionResponse(version=application_version())
