"""Validate configuration once, capture it, then own background measurement tasks."""

import asyncio
from dataclasses import asdict

from app.core.errors import ConfigurationError
from app.domain.sentiment import PROMPT_VERSION
from app.domain.seo_answer import SeoConnectionSnapshot
from app.integrations.sentiment import LlmSentimentClassifier
from app.service.measurement_worker import MeasurementWorker


class MeasurementService:
    def __init__(
        self,
        repository,
        projects,
        connections,
        seo_settings,
        search_settings,
        provider_factory,
    ):
        self.repository, self.projects, self.connections = (
            repository,
            projects,
            connections,
        )
        self.seo_settings, self.search_settings, self.provider_factory = (
            seo_settings,
            search_settings,
            provider_factory,
        )
        self.tasks = {}
        self.events = {}

    async def start(self, project_id):
        p = self.projects.get(project_id)
        p = {
            k: v
            for k, v in p.items()
            if k not in ("id", "created_at", "updated_at", "revision")
        }
        if not p["queries"] or not p["connection_ids"]:
            raise ConfigurationError("Добавьте запросы и выберите модели в проекте")
        snapshots, keys = [], {}
        for id in p["connection_ids"]:
            c = self.connections.require(id)
            key = self.connections.api_key(id)
            if not key:
                raise ConfigurationError(f"Добавьте API-ключ модели «{c.name}»")
            snapshots.append(
                SeoConnectionSnapshot(
                    c.id,
                    c.name,
                    c.kind,
                    c.endpoint or "",
                    c.model,
                    c.answer_mode,
                    c.thinking_disabled,
                )
            )
            keys[id] = key
        client = self.seo_settings.build_client()
        if client is None:
            raise ConfigurationError(
                "Настройте служебную LLM для определения тональности"
            )
        gateway = None
        if p["yandex_enabled"]:
            self.search_settings.public()  # Resolve current credentials before capturing gateway.
            gateway = self.search_settings.gateway_snapshot()
            if not self.search_settings.enabled() or gateway is None:
                raise ConfigurationError("Настройте и включите поиск Яндекса")
        snapshot = {
            "project": p,
            "connections": [asdict(c) for c in snapshots],
            "classifier": {
                "endpoint": client.endpoint,
                "model": client.model,
                "prompt_version": PROMPT_VERSION,
            },
            "yandex": {"region": p["yandex_region"], "mode": "async"}
            if gateway
            else None,
            "metric_version": "project-metrics-v2",
        }
        count = len(p["queries"]) * len(snapshots)
        estimate = {
            "model_calls": count,
            "sentiment_calls": count,
            "search_calls": len(p["queries"]) if gateway else 0,
        }
        id = self.repository.create(project_id, snapshot, estimate)
        providers = {}
        try:
            for c in snapshots:
                providers[c.connection_id] = self.provider_factory(
                    c, keys[c.connection_id]
                )
        except Exception:  # noqa: BLE001 - adapter setup must not expose credentials
            for provider in providers.values():
                provider.close()
            self.repository.finish(id, "failed")
            raise ConfigurationError("Не удалось подготовить модели замера") from None
        event = asyncio.Event()
        self.events[id] = event
        task = asyncio.create_task(
            MeasurementWorker(self.repository).run(
                id,
                event,
                providers,
                LlmSentimentClassifier(
                    client, p.get("brand_aliases", []), p.get("brand_description", "")
                ),
                gateway,
            )
        )
        self.tasks[id] = task

        def finished(done):
            if not done.cancelled():
                done.exception()  # Consume failures even if storage became unavailable.
            self.tasks.pop(id, None)
            self.events.pop(id, None)

        task.add_done_callback(finished)
        return {
            "id": id,
            "project_id": project_id,
            "status": "running",
            "estimate": estimate,
        }

    def get(self, id):
        return self.repository.get(id)

    def list_page(self, project_id, cursor=None, limit=20):
        self.projects.get(project_id)
        return self.repository.list_page(project_id, cursor, limit)

    def rows_page(self, id, kind, cursor=None, limit=50):
        return self.repository.rows_page(id, kind, cursor, limit)

    def cancel(self, id):
        result = self.repository.cancel(id)
        if id in self.events:
            self.events[id].set()
        return result

    def delete(self, id):
        self.repository.delete(id)

    async def close(self):
        for event in self.events.values():
            event.set()
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
