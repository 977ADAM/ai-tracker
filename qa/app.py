"""The application under test.

The suite never starts anything. It checks an instance the developer already
runs, exactly as a person would open it, and only needs to know where it lives.
Point it elsewhere with `QA_BASE_URL` and `QA_API_URL`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://127.0.0.1:5173"
DEFAULT_API_URL = "http://127.0.0.1:8000"

BASE_URL_VARIABLE = "QA_BASE_URL"
API_URL_VARIABLE = "QA_API_URL"

PROBE_TIMEOUT = 3.0
REQUEST_TIMEOUT = 5.0


@dataclass(frozen=True)
class Application:
    """Where the browser should go, and how to reach the Python API directly."""

    base_url: str
    api_url: str

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def connections(self) -> list[dict]:
        """Read the connection list straight from the Python API."""
        with urllib.request.urlopen(f"{self.api_url}/api/providers", timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def forget(self, connection_id: str) -> None:
        """Delete a connection through the API, which also drops its stored key."""
        request = urllib.request.Request(f"{self.api_url}/api/providers/{connection_id}", method="DELETE")
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            response.read()


def configured_application() -> Application:
    return Application(
        base_url=os.getenv(BASE_URL_VARIABLE, DEFAULT_BASE_URL).rstrip("/"),
        api_url=os.getenv(API_URL_VARIABLE, DEFAULT_API_URL).rstrip("/"),
    )


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def missing_services(application: Application) -> list[str]:
    """Names of the services that are not answering, in the order they are needed."""
    probes = (
        ("Python API", f"{application.api_url}/api/providers"),
        ("интерфейс SvelteKit", application.url("/")),
    )
    return [name for name, url in probes if not reachable(url)]
