"""The manual JSON contract and the agent-facing types of the SEO service LLM."""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from app.core.errors import ValidationError
from app.domain import seo_llm
from app.domain.seo_llm import (
    AgentMessage,
    AgentModel,
    AgentTurn,
    ToolCall,
    ToolSchema,
    parse_json_object,
)

OBJECT = '{"company_name": "Ромашка", "services": ["доставка"]}'


def test_reads_a_plain_object():
    assert parse_json_object(OBJECT) == {"company_name": "Ромашка", "services": ["доставка"]}


@pytest.mark.parametrize(
    "text",
    [
        f"```json\n{OBJECT}\n```",
        f"```\n{OBJECT}\n```",
        f"```JSON {OBJECT} ```",
    ],
)
def test_reads_a_markdown_fenced_object(text):
    assert parse_json_object(text) == {"company_name": "Ромашка", "services": ["доставка"]}


@pytest.mark.parametrize(
    "text",
    [
        f"Вот результат:\n{OBJECT}\nГотово.",
        f"Вот результат:\n```json\n{OBJECT}\n```\nГотово.",
        f"Ответ модели: {OBJECT}",
    ],
)
def test_reads_an_object_wrapped_in_prose(text):
    assert parse_json_object(text) == {"company_name": "Ромашка", "services": ["доставка"]}


def test_reads_nested_values_unchanged():
    text = 'prefix {"a": {"b": [1, 2, {"c": null}]}, "d": true} suffix'

    assert parse_json_object(text) == {"a": {"b": [1, 2, {"c": None}]}, "d": True}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "\n\t ",
        "not json at all",
        "{broken",
        '{"a": 1,}',
        "{'a': 1}",
        "```json\nnot json\n```",
    ],
)
def test_invalid_json_is_a_domain_error(text):
    with pytest.raises(ValidationError):
        parse_json_object(text)


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2, 3]",
        "```json\n[1, 2, 3]\n```",
        "null",
        '"text"',
    ],
)
def test_non_object_json_is_a_domain_error(text):
    with pytest.raises(ValidationError):
        parse_json_object(text)


@pytest.mark.parametrize("value", [None, 42, ["{}"]])
def test_non_string_input_is_a_domain_error(value):
    with pytest.raises(ValidationError):
        parse_json_object(value)


def test_a_tool_call_keeps_its_id_name_and_argument_object():
    call = ToolCall(id="call_1", name="lookup", arguments={"query": "доставка", "limit": 3})

    assert (call.id, call.name) == ("call_1", "lookup")
    assert call.arguments == {"query": "доставка", "limit": 3}


def test_an_agent_turn_defaults_to_no_tool_calls():
    assert AgentTurn(text="Готово") == AgentTurn(text="Готово", tool_calls=())


def test_an_agent_turn_holds_calls_in_order():
    first = ToolCall(id="call_1", name="first", arguments={})
    second = ToolCall(id="call_2", name="second", arguments={})

    turn = AgentTurn(text="", tool_calls=(first, second))

    assert turn.text == ""
    assert turn.tool_calls == (first, second)


def test_an_agent_message_is_a_role_and_content_by_default():
    message = AgentMessage(role="user", content="Найди конкурентов")

    assert (message.role, message.content) == ("user", "Найди конкурентов")
    assert message.tool_call_id is None
    assert message.tool_calls == ()


def test_an_agent_message_can_carry_a_tool_result_and_assistant_calls():
    call = ToolCall(id="call_1", name="lookup", arguments={})

    result = AgentMessage(role="tool", content='{"ok": true}', tool_call_id="call_1")
    assistant = AgentMessage(role="assistant", content="", tool_calls=(call,))

    assert result.tool_call_id == "call_1"
    assert assistant.tool_calls == (call,)


@pytest.mark.parametrize("role", ["", "function", "developer", "assistant ", None, 5])
def test_an_agent_message_rejects_an_unknown_role(role):
    with pytest.raises(ValidationError):
        AgentMessage(role=role, content="text")


def test_a_tool_schema_keeps_the_json_schema_of_its_arguments():
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    schema = ToolSchema(name="lookup", description="Найти домен", parameters=parameters)

    assert (schema.name, schema.description) == ("lookup", "Найти домен")
    assert schema.parameters == parameters
    assert ToolSchema(name="ping", description="Пинг").parameters == {}


def test_the_agent_types_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ToolCall(id="call_1", name="lookup", arguments={}).name = "other"


class _StepOnlyModel:
    async def step(self, messages, tools):
        return AgentTurn(text="ok")


def test_a_step_only_model_satisfies_the_agent_model_protocol():
    assert isinstance(_StepOnlyModel(), AgentModel)


def test_the_domain_stays_free_of_model_libraries():
    assert "langchain" not in inspect.getsource(seo_llm).lower()
