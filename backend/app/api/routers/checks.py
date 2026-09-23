"""Brand check endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import CheckServiceDep
from app.api.schemas import CheckRequest, CheckResponse, ErrorResponse

router = APIRouter(tags=["checks"])


@router.post(
    "/check",
    response_model=CheckResponse,
    summary="Проверить упоминания бренда",
    responses={
        400: {"model": ErrorResponse, "description": "Некорректный запрос или неизвестное подключение"},
        503: {"model": ErrorResponse, "description": "Локальное хранилище настроек недоступно"},
    },
)
def run_check(checks: CheckServiceDep, payload: CheckRequest) -> dict[str, Any]:
    """Run the same prompts against every selected connection."""
    return checks.run(payload.model_dump(exclude_unset=True))
