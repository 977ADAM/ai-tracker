"""Sequential fixed-query measurement, with durable boundaries before each call."""

import asyncio
import logging

from app.core.errors import AppError, RunNotFound

log = logging.getLogger(__name__)


def safe_error(error, fallback):
    return str(error) if isinstance(error, AppError) else fallback


class MeasurementWorker:
    def __init__(self, repository):
        self.repository = repository

    async def run(self, id, cancel_event, providers, classifier, gateway=None):
        deferred_close = set()
        try:
            if cancel_event.is_set():
                return
            p = self.repository.get(id)["snapshot"]["project"]
            for i, q in enumerate(p["queries"]):
                for connection_id, provider in providers.items():
                    if cancel_event.is_set() or not self.repository.mark_sent(
                        id, "model", (i, connection_id)
                    ):
                        return
                    key = (i, connection_id)
                    task = asyncio.create_task(
                        asyncio.to_thread(provider.answer, q["text"])
                    )
                    try:
                        answer = await asyncio.wait_for(asyncio.shield(task), 120)
                    except (TimeoutError, asyncio.CancelledError):
                        # A Python thread cannot be killed; never close its client while in use.
                        deferred_close.add(connection_id)

                        def close_late(done, client=provider):
                            try:
                                done.exception()
                            except asyncio.CancelledError:
                                log.debug("Вызов модели отменён")
                            try:
                                client.close()
                            except Exception:  # noqa: BLE001 - external client boundary; safe diagnostics only
                                log.warning("Не удалось закрыть клиент замера")

                        task.add_done_callback(close_late)
                        self.repository.save_answer(
                            id,
                            key,
                            None,
                            "Вызов модели прерван или превысил 120 секунд",
                        )
                        self.repository.finish(id, "interrupted")
                        return
                    except Exception as exc:  # noqa: BLE001 - keep one external failure isolated
                        self.repository.save_answer(
                            id,
                            key,
                            None,
                            safe_error(exc, "Не удалось получить ответ модели"),
                        )
                        continue
                    if not self.repository.save_answer(id, key, answer):
                        return
                    if cancel_event.is_set():
                        return
                    if self.repository.mark_sent(id, "sentiment", key):
                        try:
                            sentiment = await asyncio.wait_for(
                                classifier.classify(p["brand"], answer.text), 120
                            )
                        except Exception as exc:  # noqa: BLE001 - keep one external failure isolated
                            self.repository.save_sentiment(
                                id,
                                key,
                                None,
                                safe_error(exc, "Не удалось определить тональность"),
                            )
                        else:
                            self.repository.save_sentiment(id, key, sentiment)
                if gateway is not None:
                    if cancel_event.is_set() or not self.repository.mark_sent(
                        id, "search", i
                    ):
                        return
                    try:
                        async with asyncio.timeout(120):
                            operation = await gateway.submit(
                                q["text"], p.get("yandex_region", 213)
                            )
                            if not self.repository.save_search_operation(
                                id, i, operation
                            ):
                                return
                            while not cancel_event.is_set():
                                docs = await gateway.result(operation)
                                if docs is not None:
                                    self.repository.save_search_result(id, i, docs)
                                    break
                                try:
                                    await asyncio.wait_for(cancel_event.wait(), 1)
                                except TimeoutError:
                                    pass
                    except Exception as exc:  # noqa: BLE001 - keep one external failure isolated
                        self.repository.save_search_result(
                            id,
                            i,
                            None,
                            safe_error(exc, "Не удалось получить результаты Яндекса"),
                        )
            if not cancel_event.is_set():
                report = self.repository.get(id)["aggregates"]
                self.repository.finish(
                    id, "completed" if report["successful"] else "failed"
                )
        except RunNotFound:
            return
        except asyncio.CancelledError:
            self.repository.finish(id, "interrupted")
        except Exception:
            log.exception("Ошибка выполнения замера")
            self.repository.finish(id, "failed")
        finally:
            for connection_id, provider in providers.items():
                if connection_id not in deferred_close:
                    try:
                        provider.close()
                    except Exception:  # noqa: BLE001 - external client boundary; safe diagnostics only
                        log.warning("Не удалось закрыть клиент замера")
