"""Safe public resource for the SEO service-LLM settings.

The key never leaves the server: the GET, PUT, and DELETE responses carry the
public projection, and the availability probe answers with a safe result.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SeoSettingsServiceDep
from app.api.schemas.seo_settings import (
    SeoSettingsResponse,
    SeoSettingsTestResponse,
    SeoSettingsWriteRequest,
)

router = APIRouter(prefix="/seo/settings", tags=["seo"])


@router.get("", response_model=SeoSettingsResponse)
def read_seo_settings(settings: SeoSettingsServiceDep) -> dict[str, object]:
    return settings.public()


@router.put("", response_model=SeoSettingsResponse)
def update_seo_settings(
    settings: SeoSettingsServiceDep, payload: SeoSettingsWriteRequest,
) -> dict[str, object]:
    return settings.update(payload.model_dump(exclude_unset=True))


@router.delete("/credentials", response_model=SeoSettingsResponse)
def reset_seo_credentials(settings: SeoSettingsServiceDep) -> dict[str, object]:
    return settings.reset_credentials()


@router.post("/test", response_model=SeoSettingsTestResponse, response_model_exclude_none=True)
async def test_seo_settings(settings: SeoSettingsServiceDep) -> dict[str, object]:
    """Probe the configured model once; the request runs while the user waits."""
    return await settings.test()
