"""Brand check endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.api.deps import CheckServiceDep

router = APIRouter(tags=["checks"])


@router.post("/check")
def run_check(checks: CheckServiceDep, payload: object = Body(...)) -> dict[str, Any]:
    """Run the same prompts against every selected connection."""
    return checks.run(payload)
