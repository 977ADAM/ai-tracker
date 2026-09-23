"""Form configuration endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import FormServiceDep
from app.api.schemas import ErrorResponse, FormResponse

router = APIRouter(tags=["form"])

UNAVAILABLE = "Локальное хранилище настроек недоступно"


@router.get(
    "/form",
    response_model=FormResponse,
    summary="Параметры страницы проверки",
    responses={503: {"model": ErrorResponse, "description": UNAVAILABLE}},
)
def read_form(form_service: FormServiceDep) -> dict[str, Any]:
    """Return the limits, provider fields, and default selection for the check page."""
    return form_service.build()
