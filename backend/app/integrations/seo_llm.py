"""Adapters for the OpenAI-compatible Chat Completions API of the SEO service LLM.

`SeoLlmClient` is the small manual client the fixed-pipeline stages used: one
system message, one user message, one text answer.

`LangChainSeoLlmClient` is the tool-calling adapter the agent runtime uses. It
wraps `langchain_openai.ChatOpenAI` over the user's Chat Completions URL and
speaks only in domain values (`AgentMessage`, `ToolSchema`, `AgentTurn`), so no
model-library type escapes into the domain. Both clients map every transport,
auth, rate-limit, and malformed-payload failure onto the same fixed Russian
messages: no upstream body, no key, and no URL ever reaches the caller.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from app.core.errors import ProviderError
from app.domain.seo_llm import AgentMessage, AgentTurn, ToolCall, ToolSchema
from app.domain.seo_settings import SeoSettings

CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 60.0
REQUEST_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=CONNECT_TIMEOUT,
    pool=CONNECT_TIMEOUT,
)

AUTHORIZATION_ERROR = "Ошибка авторизации: проверьте ключ API"
RATE_LIMIT_ERROR = "Превышен лимит запросов API. Повторите позже"
UNAVAILABLE_ERROR = "Сервис модели временно недоступен"
CONNECTION_ERROR = "Не удалось установить соединение с API модели"
PAYLOAD_ERROR = "Некорректный ответ API модели"

CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
DEFAULT_TIMEOUT = 120.0


class SeoLlmClient:
    """Sends one system and one user message and returns the assistant text."""

    def __init__(self, endpoint: str, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.client = client

    async def complete(self, system: str, user: str) -> str:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                json=body,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            raise ProviderError(CONNECTION_ERROR) from exc

        self._check_status(response)
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty answer")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError(PAYLOAD_ERROR) from exc
        return content

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderError(AUTHORIZATION_ERROR)
        if response.status_code == 429:
            raise ProviderError(RATE_LIMIT_ERROR)
        if not 200 <= response.status_code < 300:
            raise ProviderError(UNAVAILABLE_ERROR)


def chat_completions_base_url(endpoint: str) -> str:
    """Return the API root `ChatOpenAI` needs for a full Chat Completions URL.

    The settings store the complete Chat Completions address, while the OpenAI
    SDK appends `/chat/completions` to the base URL it is given.
    """
    trimmed = endpoint.rstrip("/").removesuffix(CHAT_COMPLETIONS_SUFFIX)
    return trimmed.rstrip("/")


class LangChainSeoLlmClient:
    """A tool-calling `AgentModel` over `ChatOpenAI` and one configured endpoint.

    One `step` is exactly one paid model call: the SDK's retries are off, the
    temperature is zero, and the timeout bounds the whole call. The tool schemas
    are handed to `bind_tools` unchanged, and the returned tool calls become
    domain `ToolCall` values.

    Every adapter owns the HTTP pool it creates. `langchain_openai` would
    otherwise hand out one process-wide cached client per endpoint, so closing a
    throwaway probe adapter would close the client of the long-lived runtime
    adapter too, and the next call of a live run would fail with
    «Cannot send a request, as the client has been closed.».
    """

    def __init__(
        self,
        settings: SeoSettings,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        model: BaseChatModel | None = None,
        http_async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.endpoint = settings.endpoint
        self.model = settings.model
        self.timeout = timeout
        self._owned_client: httpx.AsyncClient | None = None
        if model is not None:
            self._model: BaseChatModel = model
        else:
            client = http_async_client
            if client is None:
                client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
                self._owned_client = client
            options: dict[str, object] = {
                "base_url": chat_completions_base_url(settings.endpoint),
                "api_key": settings.api_key,
                "model": settings.model,
                "temperature": 0,
                "timeout": timeout,
                "max_retries": 0,
                "use_responses_api": False,
                "http_async_client": client,
            }
            self._model = ChatOpenAI(**options)

    @property
    def chat_model(self) -> BaseChatModel:
        """The wrapped model, for a graph that builds its own specialist nodes."""
        return self._model

    async def step(
        self, messages: Sequence[AgentMessage], tools: Sequence[ToolSchema],
    ) -> AgentTurn:
        """Make one model call and map the answer onto the agent contract."""
        bound = self._model.bind_tools(openai_tools(tools)) if tools else self._model
        try:
            answer = await bound.ainvoke(langchain_messages(messages))
        except openai.AuthenticationError as exc:
            raise ProviderError(AUTHORIZATION_ERROR) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError(AUTHORIZATION_ERROR) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(RATE_LIMIT_ERROR) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(CONNECTION_ERROR) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(UNAVAILABLE_ERROR) from exc
        except Exception as exc:
            # A malformed body fails deep inside the SDK; its text may quote it.
            raise ProviderError(PAYLOAD_ERROR) from exc
        return agent_turn(answer)

    async def aclose(self) -> None:
        """Close the HTTP client this adapter created, and nothing else.

        An adapter built over an injected client, or over a model handed in from
        outside, does not own that client: the caller closes it.
        """
        client = self._owned_client
        self._owned_client = None
        if client is not None:
            await client.aclose()


def provider_error(error: BaseException) -> ProviderError | None:
    """Map one provider or transport failure onto a fixed safe message.

    `None` means "not a provider failure": a bug in our own code keeps its own
    exception instead of being disguised as an upstream problem. Nothing of the
    original text, URL, or key survives the mapping.
    """
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderError(AUTHORIZATION_ERROR)
    if isinstance(error, openai.RateLimitError):
        return ProviderError(RATE_LIMIT_ERROR)
    if isinstance(error, (openai.APIConnectionError, httpx.HTTPError, TimeoutError)):
        return ProviderError(CONNECTION_ERROR)
    if isinstance(error, openai.APIStatusError):
        return ProviderError(UNAVAILABLE_ERROR)
    if isinstance(error, openai.OpenAIError):
        return ProviderError(PAYLOAD_ERROR)
    return None


def openai_tools(tools: Sequence[ToolSchema]) -> list[dict[str, object]]:
    """Render domain tool schemas in the OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }
        for tool in tools
    ]


def langchain_messages(messages: Sequence[AgentMessage]) -> list[BaseMessage]:
    """Render the domain dialogue as LangChain chat messages."""
    rendered: list[BaseMessage] = []
    for message in messages:
        if message.role == "system":
            rendered.append(SystemMessage(message.content))
        elif message.role == "user":
            rendered.append(HumanMessage(message.content))
        elif message.role == "tool":
            rendered.append(ToolMessage(message.content, tool_call_id=message.tool_call_id or ""))
        else:
            rendered.append(assistant_message(message))
    return rendered


def assistant_message(message: AgentMessage) -> AIMessage:
    """Render a domain assistant message, with its tool calls when it has any."""
    if not message.tool_calls:
        return AIMessage(message.content)
    calls = [
        {
            "name": call.name,
            "args": dict(call.arguments),
            "id": call.id,
            "type": "tool_call",
        }
        for call in message.tool_calls
    ]
    return AIMessage(content=message.content, tool_calls=calls)


def agent_turn(answer: object) -> AgentTurn:
    """Map one provider answer onto `AgentTurn`, or fail with a safe error.

    A provider that answers with unparsable tool arguments, with arguments that
    are not a JSON object, or with something that is not an assistant message
    gives no trustworthy turn, so it becomes a fixed payload error.
    """
    if not isinstance(answer, AIMessage) or answer.invalid_tool_calls:
        raise ProviderError(PAYLOAD_ERROR)
    calls: list[ToolCall] = []
    for call in answer.tool_calls:
        name = call.get("name")
        arguments = call.get("args")
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ProviderError(PAYLOAD_ERROR)
        call_id = call.get("id")
        calls.append(
            ToolCall(
                id=call_id if isinstance(call_id, str) else "",
                name=name,
                arguments=dict(arguments),
            ),
        )
    return AgentTurn(text=message_text(answer.content), tool_calls=tuple(calls))


def message_text(content: object) -> str:
    """Flatten assistant content, which a provider may return as blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""
