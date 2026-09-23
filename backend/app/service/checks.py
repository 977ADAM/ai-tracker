"""Check use case: run every selected connection against the same prompts."""

from __future__ import annotations

from typing import Any

from app.core.errors import (
    AppError,
    ConfigurationError,
    ProviderError,
    StorageError,
    ValidationError,
)
from app.domain import report
from app.domain.matching import mentions_brand
from app.domain.models import (
    RESULT_ABSENT,
    RESULT_ERROR,
    RESULT_MENTIONED,
    CheckInput,
    CheckReport,
    Connection,
    PromptResult,
    ProviderCheck,
)
from app.domain.providers import AnswerProvider, ProviderFactory
from app.domain.requests import normalize_check_request, normalize_provider_ids
from app.service.connections import ConnectionService

MISSING_KEY_MESSAGE = "Добавьте API-ключ в настройках подключения"
SETUP_FAILURE_MESSAGE = "Не удалось подготовить подключение к API модели"
CALL_FAILURE_MESSAGE = "Не удалось получить ответ API модели"
UNKNOWN_CONNECTION_MESSAGE = "Выбрано неизвестное подключение"


class CheckService:
    """Runs one check request. A failing connection never erases another's results."""

    def __init__(self, connections: ConnectionService, factory: ProviderFactory) -> None:
        self.connections = connections
        self.factory = factory

    def run(self, payload: object) -> dict[str, Any]:
        check_input = normalize_check_request(payload)
        selected_ids = normalize_provider_ids(payload)
        known = self._known_connections()
        if any(connection_id not in known for connection_id in selected_ids):
            raise ValidationError(UNKNOWN_CONNECTION_MESSAGE)

        checks = tuple(
            self._run_connection(known[connection_id], check_input) for connection_id in selected_ids
        )
        return CheckReport(
            brand=check_input.brand,
            domain=check_input.domain,
            checks=checks,
            summary=report.summarize(checks),
        ).as_dict()

    def _known_connections(self) -> dict[str, Connection]:
        try:
            return {connection.id: connection for connection in self.connections.all()}
        except StorageError as exc:
            raise ConfigurationError(str(exc)) from exc

    def _run_connection(self, connection: Connection, check_input: CheckInput) -> ProviderCheck:
        provider, setup_error = self._prepare(connection)
        results: list[PromptResult] = []
        try:
            for prompt in check_input.prompts:
                results.append(self._ask(provider, setup_error, prompt, check_input.brand))
        finally:
            self._close(provider)
        return ProviderCheck(
            provider_id=connection.id,
            provider_name=connection.name,
            results=tuple(results),
        )

    def _prepare(self, connection: Connection) -> tuple[AnswerProvider | None, str | None]:
        """Build the adapter, or return the message that every prompt will report."""
        try:
            key = self.connections.api_key(connection.id)
            if not key:
                return None, MISSING_KEY_MESSAGE
            return self.factory(connection, key), None
        except AppError as exc:
            return None, str(exc)
        except Exception:
            # An unexpected adapter or credential failure must still not leak
            # internals, and must only affect this connection's result group.
            return None, SETUP_FAILURE_MESSAGE

    def _ask(
        self,
        provider: AnswerProvider | None,
        setup_error: str | None,
        prompt: str,
        brand: str,
    ) -> PromptResult:
        if setup_error is not None or provider is None:
            return self._failure(prompt, setup_error or SETUP_FAILURE_MESSAGE)
        try:
            answer = provider.answer(prompt)
        except ProviderError as exc:
            return self._failure(prompt, str(exc))
        except Exception:
            # Same rule as _prepare: a broken adapter is a failed prompt, never
            # a stack trace and never a negative mention.
            return self._failure(prompt, CALL_FAILURE_MESSAGE)
        if not isinstance(answer, str) or not answer.strip():
            return self._failure(prompt, CALL_FAILURE_MESSAGE)
        mentioned = mentions_brand(answer, brand)
        return PromptResult(
            prompt=prompt,
            answer=answer,
            mentioned=mentioned,
            error=None,
            status=RESULT_MENTIONED if mentioned else RESULT_ABSENT,
        )

    @staticmethod
    def _failure(prompt: str, message: str) -> PromptResult:
        return PromptResult(
            prompt=prompt,
            answer=None,
            mentioned=None,
            error=message,
            status=RESULT_ERROR,
        )

    @staticmethod
    def _close(provider: AnswerProvider | None) -> None:
        if provider is None:
            return
        try:
            provider.close()
        except Exception:
            # Releasing HTTP resources is best effort: a close failure must not
            # replace the results the run already collected.
            pass
