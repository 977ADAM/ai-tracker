"""OpenAPI document assembly."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# FastAPI advertises 422 for every operation with a body. Request schema
# violations are answered with 400 instead (see `errors.request_validation_handler`),
# so the entry would describe a response this API never sends.
SUPERSEDED_STATUS = "422"


def openapi_builder(application: FastAPI, *, title: str, version: str) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(title=title, version=version, routes=application.routes)
        for operations in schema.get("paths", {}).values():
            for operation in operations.values():
                operation.get("responses", {}).pop(SUPERSEDED_STATUS, None)
        application.openapi_schema = schema
        return schema

    return build


def install_openapi(application: FastAPI, *, title: str, version: str) -> None:
    application.openapi = openapi_builder(application, title=title, version=version)
