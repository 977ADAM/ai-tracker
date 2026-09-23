"""Maps application errors onto the HTTP responses the browser already expects."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ConfigurationError, StorageError, ValidationError

log = logging.getLogger("ai_tracker")

# The BFF reads a plain string `detail`, so every handler below keeps that shape.
STATUS_BY_ERROR: tuple[tuple[type[AppError], int], ...] = (
    (ValidationError, 400),
    (ConfigurationError, 400),
    (StorageError, 503),
)

INVALID_REQUEST_MESSAGE = "Некорректный запрос"
INVALID_FIELD_TEMPLATE = "Некорректное поле «{field}»"


def status_for(error: AppError) -> int:
    for error_type, status in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return status
    return 400


def _field_path(error: RequestValidationError) -> str:
    """Name the offending body field without echoing the value the client sent."""
    errors = error.errors()
    if not errors:
        return ""
    location = errors[0].get("loc") or ()
    return ".".join(str(part) for part in location if part not in ("body", "query", "path"))


async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    """Report an expected application error with its user-facing message."""
    return JSONResponse({"detail": str(error)}, status_code=status_for(error))


async def request_validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    """Keep schema rejections at 400 with a readable message.

    FastAPI defaults to 422 with a list of machine-readable errors. The browser
    BFF only understands a string `detail`, and the check page already treats
    400 as "исправьте ввод", so schema violations are folded into that contract.
    """
    field = _field_path(error)
    message = INVALID_FIELD_TEMPLATE.format(field=field) if field else INVALID_REQUEST_MESSAGE
    return JSONResponse({"detail": message}, status_code=400)


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    """Keep an unexpected crash JSON-shaped and free of internals."""
    log.exception("Необработанная ошибка при обработке %s", request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервиса"}, status_code=500)
