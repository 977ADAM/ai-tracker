"""Isolated real project backend with deterministic outbound adapters for QA."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.main import app
from app.api.deps import build_container
from app.core.config import Settings
from tests.fakes import MemorySecrets


class Provider:
    def answer(self, prompt):
        return "Додопицца — хороший выбор.\n\nДоставляет пиццу."

    def close(self):
        pass


class ClassifierClient:
    endpoint = "https://api.example.com/chat/completions"
    model = "test-judge"

    async def complete(self, system, user):
        return json.dumps(
            {"label": "positive", "evidence": "Додопицца — хороший выбор."},
            ensure_ascii=False,
        )


class ClassifierSettings:
    def build_client(self):
        return ClassifierClient()


container = build_container(
    Settings(config_dir=Path(os.environ["AI_TRACKER_CONFIG_DIR"]), presets=()),
    secrets=MemorySecrets(),
    provider_factory=lambda c, k: Provider(),
)
container.connections.save(
    {
        "name": "QA модель",
        "kind": "openai",
        "endpoint": "https://api.example.com/chat/completions",
        "model": "qa",
        "api_key": "fake-key",
    }
)
container.measurements.seo_settings = ClassifierSettings()
app.state.container = container
