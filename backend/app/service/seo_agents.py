"""The LangGraph supervisor runtime of the SEO agents: graph, bridge, and entry point.

One run is one `StateGraph` over a shared message state: a `supervisor` node and
five specialist nodes. The supervisor does no work itself — it asks the service
LLM which control tool to use (`handoff_to`, `finish_run`, `read_status`), every
control call goes through `SeoToolbox` (so it is budgeted and traced), and its
result decides the next node. A specialist node runs a bounded tool-calling loop
over its own tool subset and returns to the supervisor, which is called again.

The agents never touch the world: `langchain_tools` bridges each server tool of
`SeoToolbox` into a LangChain tool with a pydantic argument schema derived from
the JSON schema of `domain.seo_tools`. A tool result is the toolbox JSON string
as is, and a tool failure is a safe JSON result — only `StorageError` and
cancellation leave the bridge, because a broken database must stop the run
instead of becoming a model-visible result.

Graph state is checkpointed into a separate SQLite file (`seo-agents.sqlite3`,
owner-only; the graph is compiled with an injected checkpointer) so a run
survives a restart. The runtime owns the happy path here: it marks the
supervisor `running`, invokes the graph under the analysis id, and — when the
supervisor called `finish_run` — closes the agents and the run as `completed`.
Budgets at node boundaries, degradations, and resume belong to the next steps,
which extend this module; without a successful `finish_run` the run stays
`running` on purpose.

Cancellation is owned here as well: `cancel(analysis_id)` sets the per-run
`asyncio.Event` and ends the analysis as `cancelled`, and the graph, the tool
bridge, and every paid boundary of `SeoToolbox` read that event, so a cancelled
run makes no further external call. A `SeoCancelled` that leaves the graph closes
every open agent as `skipped` and never rewrites the `cancelled` status.

Every model turn is traced as a `model` step through `ModelTracer`, one wrapper
per agent, so a turn records the acting agent and whether the turn asked for a
tool or answered. Answer text is never stored: the toolbox already persists
every tool result. The graph-level backstop of `max_supervisor_turns` ends the
graph without finishing the run — only `finish_run` finishes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Any, Protocol, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, create_model

from app.core.errors import AppError, RunConflict, StorageError
from app.db.seo import SeoRepository
from app.domain.seo import AGENTS, SeoInput
from app.domain.seo_llm import AgentModel, ToolSchema
from app.domain.seo_prompts import (
    check_agent_prompt,
    competitor_agent_prompt,
    query_agent_prompt,
    report_agent_prompt,
    site_agent_prompt,
    supervisor_prompt,
)
from app.domain.seo_tools import CANCELLED, BudgetExceeded, SeoBudget, SeoCancelled
from app.service.seo_tools import SeoToolbox

LOGGER = logging.getLogger(__name__)

# The checkpoint file lives beside `runs.sqlite3` and never inside it: graph
# state is disposable, the analysis rows are not.
CHECKPOINT_FILE_NAME = "seo-agents.sqlite3"
CHECKPOINT_FILE_MODE = 0o600
CHECKPOINT_DIR_MODE = 0o700

SUPERVISOR_NODE = "supervisor"
SPECIALIST_NODES: tuple[str, ...] = tuple(agent for agent in AGENTS if agent != SUPERVISOR_NODE)
DEFAULT_MAX_SUPERVISOR_TURNS = 15
# One supervisor turn costs a handful of graph steps; the limit only has to stay
# out of the way, because `max_supervisor_turns` is the real ceiling.
RECURSION_STEPS_PER_TURN = 4
RECURSION_HEADROOM = 25

NEXT_END = "end"
NEXT_SUPERVISOR = "supervisor"

STEP_MODEL = "model"

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# One model turn is `done` when it ends the agent loop with an answer and
# `running` when it asks for a tool and the loop continues; both are words of the
# stored `STEP_STATUSES` vocabulary, so a model step is a trace step like any
# other. The distinction is what the trace shows for a turn, not the answer text.
STATUS_WITH_TOOL_CALL = "running"
STATUS_WITHOUT_TOOL_CALL = "done"

HANDOFF_TOOL = "handoff_to"
FINISH_TOOL = "finish_run"
REPORT_AGENT = "report"
CHECK_AGENT = "checks"
SITE_AGENT = "site"
FATAL_DATA_MISSING = "Не собраны сведения о сайте или не сгенерированы запросы"

SEARCH_FAILED = "Инструмент временно недоступен"
SUPERVISOR_FAILED = "Супервизор SEO-анализа завершился ошибкой"
STORAGE_FAILED = "Ошибка сохранения SEO-анализа"
UNKNOWN_SPECIALIST = "У агента нет задачи"
MODEL_UNSUPPORTED = "Модель агентов не поддерживает LangGraph"
TASK_PREFIX = "Задача агента"


class RunState(TypedDict):
    """State of one agent run: the dialogue, the next node, and the finish flag.

    `messages` is the shared, checkpointed dialogue. `supervisor_next` is the
    routing decision of the last supervisor turn: a specialist name, `end`, or
    `supervisor` to ask the supervisor again. `specialists` counts the finished
    visits per specialist, which is the graph-level backstop of the handoff
    budget.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    supervisor_next: str
    finished: bool
    finish_reason: str
    specialists: dict[str, int]


class AgentPrompts(Protocol):
    """The prompt builders the graph needs, injectable for tests and reuse."""

    def supervisor(
        self, input: SeoInput, status: Mapping[str, object], budget: Mapping[str, object],
    ) -> tuple[str, str]: ...

    def specialist(self, agent: str, input: SeoInput) -> tuple[str, str]: ...

    def report(self, metrics: Mapping[str, object]) -> tuple[str, str]: ...


class SeoPrompts:
    """The default prompts: the six builders of `domain.seo_prompts` as one object."""

    def supervisor(
        self, input: SeoInput, status: Mapping[str, object], budget: Mapping[str, object],
    ) -> tuple[str, str]:
        return supervisor_prompt(input, budget, status)

    def specialist(self, agent: str, input: SeoInput) -> tuple[str, str]:
        builders: Mapping[str, Callable[[SeoInput], tuple[str, str]]] = {
            "site": site_agent_prompt,
            "competitors": competitor_agent_prompt,
            "queries": query_agent_prompt,
            "checks": check_agent_prompt,
        }
        builder = builders.get(agent)
        if builder is None:
            raise AppError(UNKNOWN_SPECIALIST)
        return builder(input)

    def report(self, metrics: Mapping[str, object]) -> tuple[str, str]:
        return report_agent_prompt(metrics)


# -- tool bridge -------------------------------------------------------------


class SeoBridgeTool(BaseTool):
    """One server tool of `SeoToolbox` exposed to a specialist's model.

    Every call goes to `SeoToolbox.call` with the acting agent, so the toolbox
    keeps validating arguments, checking budgets, persisting results, and
    appending trace steps. Its answer is returned unchanged: it is already a
    compact JSON string with a safe refusal or a safe error. A `StorageError`
    (and cancellation) still propagates, because a broken database must stop the
    run instead of becoming a model-visible result.
    """

    toolbox: SeoToolbox
    agent: str

    async def _arun(self, **arguments: object) -> str:
        if self.toolbox.cancelled():
            raise SeoCancelled(CANCELLED)
        try:
            return await self.toolbox.call(
                self.name, _tool_arguments(arguments), agent=self.agent,
            )
        except (StorageError, SeoCancelled, AppError):
            raise
        except Exception:  # noqa: BLE001 - a broken tool is a safe result, not a crash
            LOGGER.error("SEO agent tool %s failed unexpectedly", self.name)
            return json.dumps({"status": "error", "error": SEARCH_FAILED}, ensure_ascii=False)

    def _run(self, **arguments: object) -> str:
        raise NotImplementedError("SEO agent tools are asynchronous only")


def _tool_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    """Flatten the tool arguments back into plain JSON values.

    The model provider sends JSON and LangChain turns nested objects into
    pydantic models, while `SeoToolbox` validates plain mappings and sequences.
    An absent optional argument arrives as `None` and is dropped, so the toolbox
    reads it as "not given" exactly as its schema declares.
    """
    return {
        str(key): _plain_value(value)
        for key, value in arguments.items()
        if value is not None
    }


def _plain_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return {str(key): _plain_value(item) for key, item in value.model_dump().items()}
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return value


def langchain_tools(toolbox: SeoToolbox, agent: str) -> list[BaseTool]:
    """Bridge the declared tools of one agent into LangChain tools.

    The argument model of every tool is derived from its `TOOL_SCHEMAS` entry:
    the descriptions, the required fields, the array and string bounds, and the
    closed nested objects are mirrored; everything the model cannot express here
    is still enforced by `SeoToolbox` before any work happens.
    """
    return [
        SeoBridgeTool(
            name=schema.name,
            description=schema.description,
            args_schema=_arguments_model(schema),
            toolbox=toolbox,
            agent=agent,
        )
        for schema in toolbox.schemas_for(agent)
    ]


def _arguments_model(schema: ToolSchema) -> type[BaseModel]:
    parameters = schema.parameters if isinstance(schema.parameters, Mapping) else {}
    properties = parameters.get("properties")
    declared = properties if isinstance(properties, Mapping) else {}
    required = parameters.get("required")
    required_names = set(required) if isinstance(required, Sequence) else set()
    fields: dict[str, tuple[type, object]] = {}
    for name, spec in declared.items():
        field_type = _python_type(spec)
        options = _field_options(spec)
        if name in required_names:
            fields[str(name)] = (field_type, Field(..., **options))
        else:
            default = spec.get("default") if isinstance(spec, Mapping) else None
            fields[str(name)] = (field_type, Field(default, **options))
    model = create_model(f"{_model_name(schema.name)}Args", **fields)  # type: ignore[call-overload]
    model.model_config["extra"] = "forbid"
    return model


def _model_name(tool_name: str) -> str:
    return "".join(part.capitalize() for part in tool_name.split("_"))


def _field_options(spec: object) -> dict[str, object]:
    document = spec if isinstance(spec, Mapping) else {}
    options: dict[str, object] = {}
    description = document.get("description")
    if isinstance(description, str) and description:
        options["description"] = description
    for source, target in (
        ("minLength", "min_length"),
        ("maxLength", "max_length"),
        ("minItems", "min_length"),
        ("maxItems", "max_length"),
        ("minimum", "ge"),
        ("maximum", "le"),
    ):
        value = document.get(source)
        if isinstance(value, int) and not isinstance(value, bool):
            options[target] = value
    return options


def _python_type(spec: object) -> type:
    document = spec if isinstance(spec, Mapping) else {}
    kind = document.get("type")
    if kind == "integer":
        return int
    if kind == "array":
        return list[_python_type(document.get("items") or {})]  # type: ignore[misc]
    if kind == "object":
        return _object_model(document)
    return str


def _object_model(document: Mapping[str, object]) -> type[BaseModel]:
    """Build the nested model of one closed JSON object argument."""
    properties = document.get("properties")
    declared = properties if isinstance(properties, Mapping) else {}
    required = document.get("required")
    required_names = set(required) if isinstance(required, Sequence) else set()
    fields: dict[str, tuple[type, object]] = {}
    for name, spec in declared.items():
        field_type = _python_type(spec)
        options = _field_options(spec)
        if name in required_names:
            fields[str(name)] = (field_type, Field(..., **options))
        else:
            default = spec.get("default") if isinstance(spec, Mapping) else None
            fields[str(name)] = (field_type, Field(default, **options))
    model = create_model("ArgumentItem", **fields)  # type: ignore[call-overload]
    model.model_config["extra"] = "forbid"
    return model


# -- model tracing -----------------------------------------------------------


class ModelTracer(BaseChatModel):
    """One agent's model plus one `model` trace step per model turn.

    `create_agent` calls the model itself, so a specialist turn can only be
    traced from inside the model. One wrapper is built per agent and already
    knows who it is acting for, so no prompt has to be matched at run time. The
    wrapper spends one turn of that agent's budget, appends one `model` step with
    the agent and the turn status, and never puts the answer text into the trace.
    """

    model: BaseChatModel
    agent: str
    recorder: Callable[[str, str], None]
    on_turn: Callable[[str], None] | None = None
    should_stop: Callable[[], bool] | None = None

    @property
    def _llm_type(self) -> str:
        return f"seo-agent-trace-{self.model._llm_type}"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        # The offered tools are the `ToolNode`'s business: the graph executes the
        # bridge tools itself. Returning the wrapper — and not a binding of the
        # inner model — is what keeps every turn visible to the trace.
        _ = (tools, kwargs)
        return self

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._spend()
        result = await self.model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self._record(result)
        return result

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._spend()
        result = self.model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self._record(result)
        return result

    def _spend(self) -> None:
        """Charge one turn; cancellation and an exhausted budget stop the graph.

        The cancellation probe runs first: after a cancel no further model call
        may be paid for, not even the one the budget would refuse anyway.
        """
        if self.should_stop is not None and self.should_stop():
            raise SeoCancelled(CANCELLED)
        if self.on_turn is not None:
            self.on_turn(self.agent)

    def _record(self, result: ChatResult) -> None:
        try:
            self.recorder(self.agent, _turn_status(result))
        except Exception:  # noqa: BLE001 - tracing must never break a paid call
            LOGGER.error("SEO model turn could not be traced")


def _turn_status(result: ChatResult) -> str:
    generation = result.generations[0] if result.generations else None
    message = generation.message if isinstance(generation, ChatGeneration) else None
    if isinstance(message, AIMessage) and message.tool_calls:
        return STATUS_WITH_TOOL_CALL
    return STATUS_WITHOUT_TOOL_CALL


# -- graph -------------------------------------------------------------------


def build_agent_graph(
    model: BaseChatModel,
    toolbox: SeoToolbox,
    *,
    checkpointer: BaseCheckpointSaver | None,
    prompts: AgentPrompts | None = None,
    max_supervisor_turns: int = DEFAULT_MAX_SUPERVISOR_TURNS,
    recursion_limit: int | None = None,
) -> Any:
    """Compile the supervisor graph over one run's toolbox.

    Every model turn is traced as a `model` step, every tool call and handoff is
    traced by `SeoToolbox`, and `finish_run` routes to `END`. The returned graph
    is invoked by `SeoAgentRuntime` with the analysis id as `thread_id` and its
    own recursion limit; the argument here only documents the expected bound.
    """
    _ = recursion_limit
    prompts = prompts if prompts is not None else SeoPrompts()

    def traced_model(agent: str) -> ModelTracer:
        """One tracing wrapper per agent, so every turn names its own actor."""
        return ModelTracer(
            model=model,
            agent=agent,
            recorder=lambda actor, status: _record_model_step(toolbox, actor, status),
            on_turn=lambda actor: _spend_turn(toolbox, actor),
            should_stop=toolbox.cancelled,
        )

    supervisor_model = traced_model(SUPERVISOR_NODE)

    async def supervisor_node(state: RunState) -> dict[str, object]:
        return await _supervisor_turn(
            state, toolbox, prompts, supervisor_model, max_supervisor_turns,
        )

    builders: dict[str, Any] = {}
    for name in SPECIALIST_NODES:
        if name == "report":
            system, _user = prompts.report({})
        else:
            system, _user = prompts.specialist(name, toolbox.input)
        builders[name] = create_agent(
            traced_model(name),
            tools=langchain_tools(toolbox, name),
            system_prompt=system,
            state_schema=RunState,
            name=name,
        )

    async def specialist_node(state: RunState) -> dict[str, object]:
        return await _specialist_node(state, builders, toolbox)

    builder: StateGraph = StateGraph(RunState)
    builder.add_node(SUPERVISOR_NODE, supervisor_node)
    for name in SPECIALIST_NODES:
        builder.add_node(name, specialist_node)
    builder.add_edge(START, SUPERVISOR_NODE)
    builder.add_conditional_edges(
        SUPERVISOR_NODE,
        _route,
        {SUPERVISOR_NODE: SUPERVISOR_NODE, NEXT_END: END, **{name: name for name in SPECIALIST_NODES}},
    )
    for name in SPECIALIST_NODES:
        builder.add_edge(name, SUPERVISOR_NODE)
    return builder.compile(checkpointer=checkpointer)


def _record_model_step(toolbox: SeoToolbox, agent: str, status: str) -> None:
    """Append one `model` trace step: who acted and how the turn ended."""
    toolbox.repository.append_step(toolbox.analysis_id, agent, STEP_MODEL, agent, status=status)


def _spend_turn(toolbox: SeoToolbox, agent: str) -> None:
    """Charge one model turn of one specialist.

    The supervisor has its own ceiling (`max_supervisor_turns`) and no per-agent
    turn row, so only specialists are charged. An exhausted turn budget raises
    `BudgetExceeded` out of the model call: the graph stops and the runtime
    publishes the run as stopped by the limit instead of looping.
    """
    if agent not in SPECIALIST_NODES:
        return
    try:
        toolbox.budget = toolbox.budget.spend_turn(agent)
    except BudgetExceeded:
        toolbox.exhausted = True
        raise


async def _supervisor_turn(
    state: RunState,
    toolbox: SeoToolbox,
    prompts: AgentPrompts,
    model: BaseChatModel,
    max_supervisor_turns: int,
) -> dict[str, object]:
    """Interpret one supervisor turn: run its control tools and route the result."""
    if toolbox.cancelled():
        raise SeoCancelled(CANCELLED)
    turns = int(state.get("specialists", {}).get(SUPERVISOR_NODE, 0))
    if turns >= max_supervisor_turns:
        # The graph-level backstop of the handoff budget: never loop forever.
        # It ends the graph and marks the run as stopped by the limit, so the
        # runtime publishes what is stored instead of leaving the run open.
        toolbox.exhausted = True
        return {"supervisor_next": NEXT_END}
    status = _toolbox_status(toolbox)
    budget = toolbox.budget.as_dict()
    system, user = prompts.supervisor(toolbox.input, status, budget)
    answer = await model.ainvoke([SystemMessage(system), *state["messages"], HumanMessage(user)])
    calls = list(getattr(answer, "tool_calls", ()) or ())
    updates: list[BaseMessage] = [answer]
    next_node = NEXT_SUPERVISOR
    task: HumanMessage | None = None
    for call in calls:
        name = str(call.get("name") or "")
        arguments = call.get("args") if isinstance(call.get("args"), dict) else {}
        result = await toolbox.call(name, arguments, agent=SUPERVISOR_NODE)
        updates.append(ToolMessage(result, tool_call_id=str(call.get("id") or ""), name=name))
        decision = _control_decision(name, result)
        if decision is None:
            continue
        if decision == NEXT_END:
            next_node = NEXT_END
            task = None
            continue
        if next_node != NEXT_END:
            next_node = decision
            task = _handoff_task(toolbox, prompts, decision)
            if decision == REPORT_AGENT:
                _complete_checks(toolbox)

    specialists = dict(state.get("specialists", {}))
    specialists[SUPERVISOR_NODE] = turns + 1
    if next_node == NEXT_END:
        return {
            "messages": updates,
            "supervisor_next": NEXT_END,
            "finished": True,
            "finish_reason": toolbox.finish_reason or "",
            "specialists": specialists,
        }
    if next_node in SPECIALIST_NODES:
        if task is not None:
            updates.append(task)
        specialists[next_node] = specialists.get(next_node, 0) + 1
        return {"messages": updates, "supervisor_next": next_node, "specialists": specialists}
    # No usable control call (a refusal or a plain answer): ask the supervisor
    # again, which either hands off or is stopped by the turn backstop.
    return {"messages": updates, "supervisor_next": NEXT_SUPERVISOR, "specialists": specialists}


def _complete_checks(toolbox: SeoToolbox) -> None:
    """Close a running checks agent: its work is done once the report starts."""
    for entry in toolbox.repository.agents(toolbox.analysis_id):
        if entry["agent"] == CHECK_AGENT and entry["status"] == STATUS_RUNNING:
            toolbox.repository.upsert_agent(toolbox.analysis_id, CHECK_AGENT, STATUS_DONE)


def _control_decision(name: str, result: str) -> str | None:
    """Read a control tool result: a specialist name, `end`, or nothing usable."""
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("status") in ("rejected", "error"):
        return None
    if name == FINISH_TOOL and payload.get("finished") is True:
        return NEXT_END
    if name == HANDOFF_TOOL:
        agent = payload.get("agent")
        return agent if isinstance(agent, str) and agent in SPECIALIST_NODES else None
    return None


def _handoff_task(toolbox: SeoToolbox, prompts: AgentPrompts, agent: str) -> HumanMessage:
    """Build the task message of one specialist visit.

    The system prompt of the visit is already part of its subgraph, so only the
    user message is built here; the report agent additionally gets the
    server-computed aggregates it explains and never recalculates.
    """
    if agent == "report":
        metrics = toolbox.repository.snapshot(toolbox.analysis_id)["aggregates"]
        _system, user = prompts.report(metrics)
    elif agent in SPECIALIST_NODES:
        _system, user = prompts.specialist(agent, toolbox.input)
    else:  # unreachable: `_control_decision` only returns declared specialists
        user = ""
    return HumanMessage(f"{TASK_PREFIX} {agent}.\n{user}")


async def _specialist_node(
    state: RunState, builders: Mapping[str, Any], toolbox: SeoToolbox,
) -> dict[str, object]:
    """Run one specialist loop and hand its dialogue back to the supervisor."""
    if toolbox.cancelled():
        # Cancelled between the handoff and this visit: do not start the loop,
        # so no tool of the specialist and no model turn of it is paid for.
        raise SeoCancelled(CANCELLED)
    agent = str(state.get("supervisor_next") or "")
    builder = builders.get(agent)
    if builder is None:  # unreachable: routing only sends known specialists
        return {"supervisor_next": NEXT_SUPERVISOR}
    messages = list(state.get("messages", []))
    task = messages[-1] if messages else HumanMessage(f"{TASK_PREFIX} {agent}.")
    result = await builder.ainvoke({"messages": [task]})
    produced = list(result.get("messages", ()))
    return {"messages": produced[1:], "supervisor_next": NEXT_SUPERVISOR}


def _route(state: RunState) -> str:
    """Route the supervisor turn: a specialist node, `END`, or the supervisor again."""
    if state.get("finished"):
        return NEXT_END
    next_node = state.get("supervisor_next") or NEXT_SUPERVISOR
    if next_node == NEXT_END:
        return NEXT_END
    if next_node in SPECIALIST_NODES:
        return next_node
    return SUPERVISOR_NODE


def _toolbox_status(toolbox: SeoToolbox) -> dict[str, object]:
    """The agent state the supervisor prompt shows: statuses and stored counts."""
    snapshot = toolbox.repository.snapshot(toolbox.analysis_id)
    return {
        "agents": [
            {"agent": entry["agent"], "status": entry["status"], "error": entry["error"]}
            for entry in snapshot["agents"]
        ],
        "stored": {
            "pages": len(snapshot["pages"]),
            "candidates": len(snapshot["candidates"]),
            "queries": len(snapshot["queries"]),
            "search_rows": snapshot["counters"]["search_rows"],
            "model_rows": snapshot["counters"]["model_rows"],
            "report_ready": snapshot["readiness"]["report_ready"],
        },
        "finished": toolbox.finished,
        "exhausted": toolbox.exhausted,
    }


# -- checkpointing -----------------------------------------------------------


def checkpoint_path(config_dir: Path | str) -> Path:
    """Return the graph checkpoint file of one config directory."""
    return Path(config_dir) / CHECKPOINT_FILE_NAME


def secure_checkpoint(path: Path | str) -> None:
    """Give the checkpoint file and its directory owner-only permissions."""
    import os

    target = Path(path)
    try:
        target.parent.mkdir(mode=CHECKPOINT_DIR_MODE, parents=True, exist_ok=True)
        os.chmod(target.parent, CHECKPOINT_DIR_MODE)
        if target.exists():
            os.chmod(target, CHECKPOINT_FILE_MODE)
    except OSError:
        LOGGER.error("SEO checkpoint permissions could not be secured")


class CheckpointFactory(Protocol):
    """Opens the graph checkpointer of one run; injectable for tests."""

    def __call__(self, analysis_id: str) -> AbstractAsyncContextManager[BaseCheckpointSaver]: ...


# -- runtime -----------------------------------------------------------------


class SeoAgentRuntime:
    """Run one SEO analysis on the supervisor graph and keep its durable state.

    The runtime owns the happy path of the run lifecycle: it marks the
    supervisor `running`, builds the graph over the toolbox of this analysis,
    invokes it under `thread_id = analysis_id`, and — when the supervisor called
    `finish_run` — closes the remaining agents and the run itself. A run without
    a successful `finish_run` is left `running`: budget finalization and the
    degradations are the next step of the plan.
    """

    def __init__(
        self,
        repository: SeoRepository,
        toolbox_factory: Callable[[str, SeoInput, SeoBudget], SeoToolbox],
        model: BaseChatModel | AgentModel,
        *,
        checkpointer: BaseCheckpointSaver | CheckpointFactory | None,
        prompts: AgentPrompts | None = None,
        max_supervisor_turns: int = DEFAULT_MAX_SUPERVISOR_TURNS,
        recursion_limit: int | None = None,
    ) -> None:
        self.repository = repository
        self.toolbox_factory = toolbox_factory
        self.model = model
        self.checkpointer = checkpointer
        self.prompts = prompts if prompts is not None else SeoPrompts()
        self.max_supervisor_turns = max_supervisor_turns
        self.recursion_limit = recursion_limit or (
            max_supervisor_turns * RECURSION_STEPS_PER_TURN + RECURSION_HEADROOM
        )
        self.chat_model = _chat_model(model)
        # One event per live analysis: `cancel` sets it, the tool bridge and the
        # graph read it before every further step and paid call.
        self._cancel_events: dict[str, asyncio.Event] = {}

    def cancel(self, analysis_id: str) -> None:
        """Stop a live run before its next step and end it as `cancelled`.

        The event is what the graph and the tools read; `SeoRepository.cancel`
        marks the analysis `cancelled` and cancels its unfinished rows. The
        repository refuses a terminal analysis, so a repeated cancel or a cancel
        of an already finished run is a safe no-op that keeps the stored status.
        """
        self._cancel_event(analysis_id).set()
        try:
            self.repository.cancel(analysis_id)
        except RunConflict:
            LOGGER.info("SEO agent run %s was already finished when cancelled", analysis_id)

    async def run(self, analysis_id: str, input: SeoInput) -> None:
        """Run the graph of one analysis; never let an exception escape the task."""
        toolbox: SeoToolbox | None = None
        try:
            self.repository.upsert_agent(analysis_id, SUPERVISOR_NODE, STATUS_RUNNING)
            toolbox = self._toolbox(analysis_id, input)
            if isinstance(self.checkpointer, BaseCheckpointSaver):
                await self._invoke(analysis_id, toolbox, input, self.checkpointer)
            else:
                async with self.checkpointer(analysis_id) as saver:
                    await self._invoke(analysis_id, toolbox, input, saver)
            self._finalize(analysis_id, toolbox)
        except SeoCancelled:
            self._finalize_cancelled(analysis_id)
        except BaseException as exc:  # a run task must never surface an exception
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            LOGGER.error("SEO agent run %s stopped: %s", analysis_id, type(exc).__name__)
            if self._cancelled(analysis_id):
                # A cancel that raced the failure still owns the outcome: the
                # run stays `cancelled` instead of turning into `failed`.
                self._finalize_cancelled(analysis_id)
            elif toolbox is not None and toolbox.exhausted:
                self._publish_exhausted(analysis_id)
            else:
                self._mark_error(analysis_id, exc)
        finally:
            self._cancel_events.pop(analysis_id, None)

    def _toolbox(self, analysis_id: str, input: SeoInput) -> SeoToolbox:
        """Build one run's toolbox and give it this run's cancellation probe."""
        toolbox = self.toolbox_factory(
            analysis_id, input, SeoBudget.for_connections(len(input.connection_ids)),
        )
        toolbox.should_stop = lambda: self._cancelled(analysis_id)
        return toolbox

    def _cancel_event(self, analysis_id: str) -> asyncio.Event:
        event = self._cancel_events.get(analysis_id)
        if event is None:
            event = self._cancel_events[analysis_id] = asyncio.Event()
        return event

    def _cancelled(self, analysis_id: str) -> bool:
        event = self._cancel_events.get(analysis_id)
        return event is not None and event.is_set()

    async def _invoke(
        self,
        analysis_id: str,
        toolbox: SeoToolbox,
        input: SeoInput,
        checkpointer: BaseCheckpointSaver | None,
    ) -> None:
        graph = self._graph(toolbox, checkpointer)
        state: RunState = {
            "messages": [HumanMessage(_run_task(input))],
            "supervisor_next": SUPERVISOR_NODE,
            "finished": False,
            "finish_reason": "",
            "specialists": {},
        }
        result = await graph.ainvoke(state, self._config(analysis_id))
        self._read_result(toolbox, result)

    async def resume(self, analysis_id: str) -> bool:
        """Continue a run from its checkpoint; `False` when there is none.

        The toolbox rebuilds its view from the stored rows, so the work of the
        interrupted run is reused instead of repeated: a search answers from the
        stored outcome, an already submitted deferred operation is polled, and an
        already answered model pair is not asked again. A run without a
        checkpoint is left to the caller (it becomes `interrupted`).
        """
        request = self._request_of(analysis_id)
        toolbox = self._toolbox(analysis_id, request)
        try:
            if isinstance(self.checkpointer, BaseCheckpointSaver):
                return await self._continue(analysis_id, toolbox, self.checkpointer)
            async with self.checkpointer(analysis_id) as saver:
                return await self._continue(analysis_id, toolbox, saver)
        except SeoCancelled:
            self._finalize_cancelled(analysis_id)
            return True
        except BaseException as exc:  # a resume task must never surface an exception
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            LOGGER.error("SEO agent resume %s stopped: %s", analysis_id, type(exc).__name__)
            if self._cancelled(analysis_id):
                self._finalize_cancelled(analysis_id)
            elif toolbox.exhausted:
                self._publish_exhausted(analysis_id)
            else:
                self._mark_error(analysis_id, exc)
            return True
        finally:
            self._cancel_events.pop(analysis_id, None)

    async def _continue(
        self, analysis_id: str, toolbox: SeoToolbox, checkpointer: BaseCheckpointSaver | None,
    ) -> bool:
        """Re-enter the graph of one run on its own thread and publish the result."""
        graph = self._graph(toolbox, checkpointer)
        config = self._config(analysis_id)
        state = await graph.aget_state(config)
        if not state.values:
            return False
        self.repository.upsert_agent(analysis_id, SUPERVISOR_NODE, STATUS_RUNNING)
        result = await graph.ainvoke(None, config)
        self._read_result(toolbox, result)
        self._finalize(analysis_id, toolbox)
        return True

    def _graph(self, toolbox: SeoToolbox, checkpointer: BaseCheckpointSaver | None) -> Any:
        return build_agent_graph(
            self.chat_model,
            toolbox,
            checkpointer=checkpointer,
            prompts=self.prompts,
            max_supervisor_turns=self.max_supervisor_turns,
            recursion_limit=self.recursion_limit,
        )

    def _config(self, analysis_id: str) -> RunnableConfig:
        return {
            "configurable": {"thread_id": analysis_id},
            "recursion_limit": self.recursion_limit,
        }

    def _read_result(self, toolbox: SeoToolbox, result: object) -> None:
        if isinstance(result, Mapping):
            toolbox.finished = bool(result.get("finished"))
            toolbox.finish_reason = str(result.get("finish_reason") or "") or toolbox.finish_reason

    def _request_of(self, analysis_id: str) -> SeoInput:
        """Rebuild the run input from the stored analysis, for a resume."""
        payload = self.repository.snapshot(analysis_id)["input"]
        return SeoInput(
            url=str(payload["url"]),
            host=str(payload["host"]),
            sphere=str(payload["sphere"]),
            seeds=tuple(str(seed) for seed in payload["seeds"]),
            services=tuple(str(service) for service in payload["services"]),
            connection_ids=tuple(str(item) for item in payload["connection_ids"]),
        )

    def _finalize(self, analysis_id: str, toolbox: SeoToolbox) -> None:
        """Publish the run: stopped by the limit, failed, or completed.

        The spec's fatal matrix is decided here, from stored rows only: the site
        agent must have saved its facts and at least five valid queries must
        exist. Candidateless runs, failed rows, a failed connection, and a
        missing report agent are not fatal — the numbers are computed from the
        stored rows, so the report is still publishable.
        """
        if toolbox.exhausted:
            self._publish_exhausted(analysis_id)
            return
        snapshot = self.repository.snapshot(analysis_id)
        agents = {str(entry["agent"]): str(entry["status"]) for entry in snapshot["agents"]}
        facts_ready = agents.get(SITE_AGENT) == STATUS_DONE
        queries_ready = bool(snapshot["readiness"].get("queries_ready"))
        self._close_agents(analysis_id, completed=True)
        if not (facts_ready and queries_ready):
            self.repository.upsert_agent(
                analysis_id, SUPERVISOR_NODE, STATUS_ERROR, error=FATAL_DATA_MISSING,
            )
            self.repository.fail_analysis(analysis_id)
            return
        if not toolbox.finished:
            LOGGER.info("SEO agent run %s stopped without finish_run; published anyway", analysis_id)
        self.repository.finish_analysis(analysis_id)

    def _publish_exhausted(self, analysis_id: str) -> None:
        """Close a run that ran out of budget: keep the rows, flag the limit."""
        try:
            self.repository.mark_budget_exhausted(analysis_id)
            self._close_agents(analysis_id, completed=True)
            self.repository.finish_analysis(analysis_id)
        except AppError:
            LOGGER.error("SEO agent run %s could not publish its budget stop", analysis_id)

    def _finalize_cancelled(self, analysis_id: str) -> None:
        """Close a cancelled run: open agents end `skipped`, the status stays.

        `repository.cancel` already stored the `cancelled` state and cancelled
        the unfinished rows; this only gives every still-open agent a terminal
        status, so nothing is left `running` and no `completed`/`failed` write
        ever replaces the cancellation.
        """
        try:
            self._close_agents(analysis_id, completed=False)
        except AppError:
            LOGGER.error("SEO agent run %s could not close its cancelled agents", analysis_id)

    def _close_agents(self, analysis_id: str, *, completed: bool) -> None:
        """Give every agent a terminal status: nothing stays `running`."""
        for entry in self.repository.agents(analysis_id):
            agent = str(entry["agent"])
            status = str(entry["status"])
            if status in (STATUS_DONE, STATUS_ERROR):
                continue
            if completed and status == STATUS_RUNNING:
                self.repository.upsert_agent(analysis_id, agent, STATUS_DONE)
            else:
                self.repository.upsert_agent(analysis_id, agent, STATUS_SKIPPED)

    def _mark_error(self, analysis_id: str, error: BaseException) -> None:
        """Record a safe supervisor error and fail this run only."""
        try:
            self.repository.upsert_agent(
                analysis_id, SUPERVISOR_NODE, STATUS_ERROR, error=_safe_error(error),
            )
            self._close_agents(analysis_id, completed=False)
            self.repository.fail_analysis(analysis_id)
        except AppError:
            LOGGER.error("SEO agent run %s could not store its error", analysis_id)


def _run_task(input: SeoInput) -> str:
    return f"Проведи SEO-анализ сайта {input.host} в сфере «{input.sphere}» и доведи прогон до отчёта."


def _chat_model(model: BaseChatModel | AgentModel) -> BaseChatModel:
    """Return the LangChain chat model behind an agent model.

    The graph and its specialist nodes need the concrete `BaseChatModel` they
    call; the production adapter exposes the one it wraps as `chat_model`, and a
    test may hand over a scripted chat model directly.
    """
    if isinstance(model, BaseChatModel):
        return model
    wrapped = getattr(model, "chat_model", None)
    if isinstance(wrapped, BaseChatModel):
        return wrapped
    raise AppError(MODEL_UNSUPPORTED)


def _safe_error(error: BaseException) -> str:
    """A fixed, safe message: no exception text, no URL, and no key reaches a row."""
    if isinstance(error, StorageError):
        return STORAGE_FAILED
    return SUPERVISOR_FAILED


__all__ = [
    "CHECKPOINT_FILE_NAME",
    "DEFAULT_MAX_SUPERVISOR_TURNS",
    "SPECIALIST_NODES",
    "SUPERVISOR_NODE",
    "AgentPrompts",
    "CheckpointFactory",
    "ModelTracer",
    "RunState",
    "SeoAgentRuntime",
    "SeoPrompts",
    "build_agent_graph",
    "checkpoint_path",
    "langchain_tools",
    "secure_checkpoint",
]
