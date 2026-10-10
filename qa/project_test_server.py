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
        if 'brand_description' in system:
            return json.dumps({'brand_description':'Сеть пиццерий','brand_aliases':['Додошка','dodo']},ensure_ascii=False)
        if '"queries"' in system:
            return json.dumps({'queries':[{'text':'Где заказать пиццу?','category':'recommendation'}]},ensure_ascii=False)
        if '"competitors"' in system:
            return '{"competitors":[]}'
        return json.dumps(
            {"label": "positive", "evidence": "Додопицца — хороший выбор."},
            ensure_ascii=False,
        )


class ClassifierSettings:
    def build_client(self):
        return ClassifierClient()

    def build_search_client(self):
        return SetupSearchClient()


class SetupSearchClient:
    async def complete_with_search(self, system, user):
        from app.domain.seo_answer import SeoAnswer, Citation
        text = await ClassifierClient().complete(system, user)
        return SeoAnswer(text, "deepseek_web", "completed", (),
                         (Citation("https://example.ru/about", "О компании", None, 0, 1),), "test", 1)


container = build_container(
    Settings(config_dir=Path(os.environ["AI_TRACKER_CONFIG_DIR"]), presets=(), database_url=os.environ["AI_TRACKER_DATABASE_URL"]),
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

container.project_generation.settings = ClassifierSettings()
