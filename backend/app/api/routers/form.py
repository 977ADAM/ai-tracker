"""Form configuration endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import FormServiceDep

router = APIRouter(tags=["form"])


@router.get("/form")
def read_form(form_service: FormServiceDep) -> dict[str, Any]:
    """Return the limits, provider fields, and default selection for the check page."""
    return form_service.build()
