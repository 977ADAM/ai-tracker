"""Local web endpoint for a one-off GigaChat brand check."""

import os
from typing import Protocol

from fastapi import Body, FastAPI, HTTPException

from .checks import mentions_brand, normalize_request
from .gigachat import GigaChatClient, ProviderError


class AnswerProvider(Protocol):
    def answer(self, prompt: str) -> str: ...


def create_app(provider: AnswerProvider | None = None) -> FastAPI:
    application = FastAPI(title="ИИ-трекинг")

    @application.post("/api/check")
    def check(payload: object = Body(...)) -> dict:
        try:
            check_input = normalize_request(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        active_provider = provider
        if active_provider is None:
            auth_key = os.getenv("GIGACHAT_AUTH_KEY")
            if not auth_key:
                raise HTTPException(status_code=503, detail="Не задан GIGACHAT_AUTH_KEY")
            active_provider = GigaChatClient(
                auth_key,
                os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                os.getenv("GIGACHAT_MODEL", "GigaChat"),
            )

        results = []
        successful = failed = mentioned = 0
        for prompt in check_input.prompts:
            try:
                answer = active_provider.answer(prompt)
            except ProviderError as exc:
                failed += 1
                results.append(
                    {"prompt": prompt, "answer": None, "mentioned": None, "error": str(exc)}
                )
                continue

            found = mentions_brand(answer, check_input.brand)
            successful += 1
            mentioned += int(found)
            results.append(
                {"prompt": prompt, "answer": answer, "mentioned": found, "error": None}
            )

        return {
            "brand": check_input.brand,
            "domain": check_input.domain,
            "results": results,
            "summary": {"successful": successful, "failed": failed, "mentioned": mentioned},
        }

    return application


app = create_app()
