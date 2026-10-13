"""The application version recorded in the backend project file."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path

_PROJECT_FILE = Path(__file__).resolve().parents[1] / "pyproject.toml"


@cache
def application_version() -> str:
    with _PROJECT_FILE.open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml has no project version")
    return version
