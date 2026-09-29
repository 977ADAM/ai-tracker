"""Manual JSON parsing of SEO service-LLM answers and the agent-facing types.

The chat contract is a text answer that contains one JSON object, so the parser
tolerates Markdown fences and surrounding prose and otherwise reports a safe
domain error.

The runtime also needs a model that answers with native tool calls. That
contract is declared here, without importing any model library: `AgentModel`
speaks only in `AgentMessage`, `ToolSchema`, and `AgentTurn` values, and the
integration layer maps them onto a concrete provider SDK.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.core.errors import ValidationError

FENCED_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
EMPTY_ANSWER = "Модель вернула пустой ответ"
INVALID_JSON = "Не удалось разобрать JSON-ответ модели"
NOT_AN_OBJECT = "Модель вернула JSON не в виде объекта"
UNKNOWN_ROLE = "Недопустимая роль сообщения агента"
# Every path that needs a configured service LLM — the run entry point, the
# agent runtime, and the build-time stand-in — reports this same fixed message.
LLM_NOT_CONFIGURED = "Не настроена служебная LLM для SEO-анализа"

AGENT_ROLES = ("system", "user", "assistant", "tool")

_MISSING = object()


def parse_json_object(text: str) -> dict[str, object]:
    """Return the JSON object inside an answer, ignoring fences and prose."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(EMPTY_ANSWER)
    candidate = _unfenced(text.strip())
    parsed = _parse(candidate)
    if parsed is _MISSING:
        braced = _outer_braces(candidate)
        parsed = _parse(braced) if braced is not None else _MISSING
    if parsed is _MISSING:
        raise ValidationError(INVALID_JSON)
    if not isinstance(parsed, dict):
        raise ValidationError(NOT_AN_OBJECT)
    return parsed


def _unfenced(text: str) -> str:
    match = FENCED_BLOCK.search(text)
    return match.group(1).strip() if match else text


def _outer_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start : end + 1]


def _parse(candidate: str) -> object:
    try:
        return json.loads(candidate)
    except ValueError:
        return _MISSING


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model asked for, with arguments already parsed.

    ``arguments`` is the JSON object the provider sent; a provider answer whose
    arguments are not a JSON object never becomes a `ToolCall`.
    """

    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class AgentTurn:
    """One assistant answer: free text, tool calls, or both."""

    text: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class AgentMessage:
    """One message of the agent dialogue, free of any model-library type.

    ``role`` is one of ``AGENT_ROLES``. ``tool_call_id`` links a ``tool`` result
    to the assistant call it answers, and ``tool_calls`` repeats the calls an
    assistant message made, so a later turn can see the same history.
    """

    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.role not in AGENT_ROLES:
            raise ValidationError(UNKNOWN_ROLE)


@dataclass(frozen=True)
class ToolSchema:
    """A tool the model may call: its name, description, and JSON schema."""

    name: str
    description: str
    parameters: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class AgentModel(Protocol):
    """A chat model that answers with text and native tool calls."""

    async def step(
        self, messages: Sequence[AgentMessage], tools: Sequence[ToolSchema],
    ) -> AgentTurn:
        """Answer the dialogue, using one of the offered tools when needed."""
        ...


async def close_agent_model(model: object) -> None:
    """Release the HTTP resources an agent model owns, if it owns any.

    An adapter built by the application holds its own HTTP pool and must be
    closed; a model handed in from outside does not implement `aclose` at all and
    is left to its owner. Releasing the pool is best effort: a broken close never
    replaces the outcome of the run that has just used the model.
    """
    aclose = getattr(model, "aclose", None)
    if not callable(aclose):
        return
    try:
        await aclose()
    except Exception:  # noqa: BLE001, S110 - releasing HTTP resources is best effort
        pass
