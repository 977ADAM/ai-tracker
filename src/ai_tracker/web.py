"""Local API and pages for checking mentions across saved AI providers."""

import os
from pathlib import Path
from typing import Callable

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .checks import mentions_brand, normalize_request
from .connections import ConnectionError, ConnectionStore, KeyringSecrets
from .gigachat import GigaChatClient
from .openai_chat import OpenAIChatClient
from .providers import AnswerProvider, ProviderError


def default_provider(connection: dict, key: str) -> AnswerProvider:
    if connection["kind"] == "gigachat":
        return GigaChatClient(key, connection.get("scope", os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")), connection["model"])
    return OpenAIChatClient(key, connection["endpoint"], connection["model"], thinking_disabled=connection["id"] == "deepseek")


def create_app(provider: AnswerProvider | None = None, store: ConnectionStore | None = None,
               provider_factory: Callable[[dict, str], AnswerProvider] | None = None,
               allowed_hosts: list[str] | None = None) -> FastAPI:
    application = FastAPI(title="ИИ-трекинг")
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["localhost", "127.0.0.1"])
    static_dir = Path(__file__).with_name("static")
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    active_store = store or ConnectionStore(Path(os.getenv("AI_TRACKER_CONFIG_DIR", Path.home() / ".config" / "ai-tracker")), KeyringSecrets())
    factory = provider_factory or default_provider

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @application.get("/settings", include_in_schema=False)
    def settings() -> FileResponse:
        return FileResponse(static_dir / "settings.html")

    @application.get("/api/providers")
    def list_providers() -> list[dict]:
        try:
            return active_store.list_connections()
        except ConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @application.post("/api/providers")
    def add_provider(payload: object = Body(...)) -> dict:
        try:
            return active_store.save_connection(payload)
        except ConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.put("/api/providers/{connection_id}")
    def update_provider(connection_id: str, payload: object = Body(...)) -> dict:
        try:
            return active_store.save_connection(payload, connection_id)
        except ConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.delete("/api/providers/{connection_id}")
    def remove_provider(connection_id: str) -> dict:
        try:
            active_store.delete_connection(connection_id)
            return {"deleted": True}
        except ConnectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/check")
    def check(payload: object = Body(...)) -> dict:
        try:
            check_input = normalize_request(payload)
            ids = payload.get("provider_ids", ["gigachat"])
            if not isinstance(ids, list) or not 1 <= len(ids) <= 5 or any(not isinstance(id, str) for id in ids) or len(ids) != len(set(ids)):
                raise ValueError("Выберите от 1 до 5 разных моделей")
            connections = {item["id"]: item for item in active_store.list_connections()}
            if any(id not in connections for id in ids):
                raise ValueError("Выбрано неизвестное подключение")
        except (ValueError, ConnectionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        checks = []
        for id in ids:
            connection = connections[id]
            client = None
            setup_error = None
            try:
                key = active_store.get_key(id)
                if provider is not None and id == "gigachat":
                    client = provider
                elif key:
                    client = factory(connection, key)
                else:
                    setup_error = "Добавьте API-ключ в настройках подключения"
            except (ConnectionError, ProviderError) as exc:
                setup_error = str(exc)

            results = []
            successful = failed = mentioned = 0
            try:
                for prompt in check_input.prompts:
                    try:
                        if setup_error:
                            raise ProviderError(setup_error)
                        answer = client.answer(prompt)
                    except ProviderError as exc:
                        failed += 1
                        results.append({"prompt": prompt, "answer": None, "mentioned": None, "error": str(exc)})
                        continue
                    found = mentions_brand(answer, check_input.brand)
                    successful += 1
                    mentioned += int(found)
                    results.append({"prompt": prompt, "answer": answer, "mentioned": found, "error": None})
            finally:
                if client is not None and client is not provider:
                    client.close()
            checks.append({"provider_id": id, "provider_name": connection["name"], "summary": {"successful": successful, "failed": failed, "mentioned": mentioned}, "results": results})

        response = {"brand": check_input.brand, "domain": check_input.domain, "checks": checks}
        if provider is not None and ids == ["gigachat"]:
            response.update({"results": checks[0]["results"], "summary": checks[0]["summary"]})
        return response

    return application


app = create_app()
