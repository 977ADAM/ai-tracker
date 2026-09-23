"""Maps application errors onto the HTTP responses the browser already expects."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ConfigurationError, StorageError, ValidationError

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
    return JSONResponse({"detail": str(error)}, status_code=status_for(error))


def register_error_handlers(application: FastAPI) -> None:
    application.add_exception_handler(AppError, app_error_handler)
