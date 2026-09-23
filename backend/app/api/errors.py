"""Maps application errors onto the HTTP responses the browser already expects."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ConfigurationError, StorageError, ValidationError

log = logging.getLogger("ai_tracker")

# The BFF reads a plain string `detail`, so every handler below keeps that shape.
STATUS_BY_ERROR: tuple[tuple[type[AppError], int], ...] = (
    (ValidationError, 400),
    (ConfigurationError, 400),
    (StorageError, 503),
)


def status_for(error: AppError) -> int:
    for error_type, status in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return status
    return 400


async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    """Report an expected application error with its user-facing message."""
    return JSONResponse({"detail": str(error)}, status_code=status_for(error))


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Keep an unexpected crash JSON-shaped and free of internals."""
    log.exception("Необработанная ошибка при обработке %s", request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервиса"}, status_code=500)
