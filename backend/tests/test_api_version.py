"""The application version comes from the backend project file."""

from __future__ import annotations

import tomllib
from pathlib import Path

from app.main import VERSION
from app.version import application_version

PROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_the_version_endpoint_reads_pyproject(client):
    with PROJECT.open("rb") as handle:
        expected = tomllib.load(handle)["project"]["version"]

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": expected}
    assert application_version() == expected == VERSION == "0.1.2"
