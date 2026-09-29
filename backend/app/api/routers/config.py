"""The configuration document of the application."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ConfigServiceDep
from app.api.schemas.config import ConfigResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
def read_config(config: ConfigServiceDep) -> dict[str, Any]:
    """Serve every stored setting — providers, search, SEO — in one document."""
    return config.read()
