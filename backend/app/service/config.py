"""Every stored setting of the application as one document.

The providers, the Yandex search settings, and the SEO service LLM live in three
files next to each other in the configuration directory. The API keys are in none
of them — the system keyring holds those — so the document is safe to show and to
copy. A file that is not valid JSON is shown as its own text instead of hiding
the sections that did parse.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.errors import ConfigurationError

# The section name in the document and the file it comes from, in the order a
# reader expects them: who answers, where the search runs, who leads the agents.
CONFIG_SECTIONS: tuple[tuple[str, str], ...] = (
    ("providers", "providers.json"),
    ("search", "search-settings.json"),
    ("seo", "seo-settings.json"),
)

MAX_CONFIG_FILE_BYTES = 256 * 1024


class ConfigService:
    """Reads the stored settings files and renders them as one JSON document."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    def read(self) -> dict[str, Any]:
        """Return the directory, whether anything is stored, and the document.

        Every section is present in the document; one that was never saved is
        `null`, so the shape does not change with the state of the directory.
        """
        stored = {section: self._text(self.config_dir / file) for section, file in CONFIG_SECTIONS}
        if all(text is None for text in stored.values()):
            return {"directory": str(self.config_dir), "exists": False, "content": None}
        document = {
            section: (None if text is None else _parsed(text))
            for section, text in stored.items()
        }
        return {
            "directory": str(self.config_dir),
            "exists": True,
            "content": json.dumps(document, ensure_ascii=False, indent=2),
        }

    @staticmethod
    def _text(path: Path) -> str | None:
        """Return the stored text, or `None` while the file does not exist."""
        try:
            if not path.is_file():
                return None
            if path.stat().st_size > MAX_CONFIG_FILE_BYTES:
                raise ConfigurationError("Файл конфигурации слишком большой")
            return path.read_text(encoding="utf-8")
        except ConfigurationError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError("Не удалось прочитать файл конфигурации") from exc


def _parsed(text: str) -> object:
    """The stored text as JSON; a broken file stays readable as its own text."""
    try:
        return json.loads(text)
    except ValueError:
        return text
