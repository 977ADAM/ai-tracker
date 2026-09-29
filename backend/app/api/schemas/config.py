"""The configuration document: every stored setting, without any secret."""

from __future__ import annotations

from pydantic import BaseModel


class ConfigResponse(BaseModel):
    """All stored settings of the app as one JSON document.

    `content` is `null` while no settings file exists yet; the document itself
    never contains an API key, because keys are held by the keyring.
    """

    directory: str
    exists: bool
    content: str | None = None
