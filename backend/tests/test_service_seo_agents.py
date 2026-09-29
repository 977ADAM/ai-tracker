"""Happy path of the LangGraph supervisor runtime on a real graph.

The suite builds the actual `StateGraph` over a real `SeoToolbox` and a scripted
`BaseChatModel`: one scripted turn per model call, in the exact order the graph
makes them (supervisor, then every specialist, then the supervisor again). Every
external collaborator is a fake and the configuration directory is temporary, so
no test reaches a paid API or the production config directory.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.errors import ProviderError
from app.db.seo import SeoRepository
from app.domain.search import SearchDocument
from app.domain.seo import SeoInput, normalize_seo_request
from app.domain.seo_tools import (
    AGENT_TOOLS,
    MAX_SPECIALIST_TURNS,
    TOOL_ARGUMENTS,
    SeoBudget,
)
from app.integrations.seo_llm import CONNECTION_ERROR
from app.service.connections import ConnectionService
from app.service.seo_agents import (
    CHECKPOINT_FILE_MODE,
    CHECKPOINT_FILE_NAME,
    ModelTracer,
    SeoAgentRuntime,
    build_agent_graph,
    checkpoint_path,
    langchain_tools,
)
from app.service.seo_tools import SeoToolbox
from tests.fakes import (
    DEFAULT_SEO_PAGE,
    FakeSiteFetcher,
    ScriptedSeoGateway,
    SeoProviderFactorySpy,
)

SEEDS = ("букет цветов", "доставка цветов", "розы")
SPHERE = "Цветочный магазин"
SERVICES = ["Букеты", "Доставка"]
CONNECTION_ID = "gigachat"
ANALYSIS_QUERIES = [
    {"query": f"купить букет {index}", "category": "commercial", "service": "Букеты"}
    for index in range(5)
]
CANDIDATES = [{"host": "rival.ru", "note": "Соперник"}]
DOCUMENTS = (
    SearchDocument("https://rival.ru/page", "Соперник — букеты"),
    SearchDocument("https://example.ru/page", "Ромашка — букеты"),
)
SUMMARY = "Ромашка упоминается в ответах частично."
RECOMMENDATIONS = "Усилить информационные запросы."
FINISH_REASON = "Отчёт сохранён"

STEP_MODEL = "model"
STEP_TOOL = "tool"
STEP_HANDOFF = "handoff"
SPECIALISTS = ("site", "competitors", "queries", "checks", "report")


def payload() -> dict[str, object]:
    return {
        "url": "https://example.ru/",
        "sphere": SPHERE,
        "seeds": list(SEEDS),
        "services": list(SERVICES),
        "connection_ids": [CONNECTION_ID],
    }


def call(name: str, **arguments: object) -> AIMessage:
    """One assistant answer that calls exactly one tool."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": dict(arguments), "id": f"call_{name}", "type": "tool_call"},
        ],
    )


def happy_path_script() -> list[AIMessage]:
    """The scripted dialogue of one complete run, in model-call order."""
    return [
        # Supervisor turn 1: the site agent.
        call("handoff_to", agent="site", reason="Собрать сведения"),
        # Site agent.
        call("fetch_site", max_pages=2),
        call("save_site_facts", company_name="Ромашка", services=["Свадьбы"]),
        AIMessage(content="Сведения о сайте сохранены"),
        # Supervisor turn 2: the competitors.
        call("handoff_to", agent="competitors", reason="Найти конкурентов"),
        # Competitor agent.
        call("yandex_search", query=SEEDS[0]),
        call("save_candidates", candidates=CANDIDATES),
        AIMessage(content="Кандидаты сохранены"),
        # Supervisor turn 3: the query agent.
        call("handoff_to", agent="queries", reason="Подготовить запросы"),
        # Query agent.
        call("save_queries", queries=ANALYSIS_QUERIES),
        AIMessage(content="Запросы сохранены"),
        # Supervisor turn 4: the check agent.
        call("handoff_to", agent="checks", reason="Запустить проверки"),
        # Check agent.
        call("search_many"),
        call("ask_models"),
        AIMessage(content="Проверки завершены"),
        # Supervisor turn 5: the report agent.
        call("handoff_to", agent="report", reason="Написать отчёт"),
        # Report agent.
        call("read_metrics"),
        call("save_report", summary=SUMMARY, recommendations=RECOMMENDATIONS),
        AIMessage(content="Отчёт сохранён"),
        # Supervisor turn 6: the end.
        call("finish_run", reason=FINISH_REASON),
    ]


HAPPY_PATH_TRACE = [
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_HANDOFF, "handoff_to"),
    ("site", STEP_MODEL, "site"),
    ("site", STEP_TOOL, "fetch_site"),
    ("site", STEP_MODEL, "site"),
    ("site", STEP_TOOL, "save_site_facts"),
    ("site", STEP_MODEL, "site"),
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_HANDOFF, "handoff_to"),
    ("competitors", STEP_MODEL, "competitors"),
    ("competitors", STEP_TOOL, "yandex_search"),
    ("competitors", STEP_MODEL, "competitors"),
    ("competitors", STEP_TOOL, "save_candidates"),
    ("competitors", STEP_MODEL, "competitors"),
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_HANDOFF, "handoff_to"),
    ("queries", STEP_MODEL, "queries"),
    ("queries", STEP_TOOL, "save_queries"),
    ("queries", STEP_MODEL, "queries"),
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_HANDOFF, "handoff_to"),
    ("checks", STEP_MODEL, "checks"),
    ("checks", STEP_TOOL, "search_many"),
    ("checks", STEP_MODEL, "checks"),
    ("checks", STEP_TOOL, "ask_models"),
    ("checks", STEP_MODEL, "checks"),
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_HANDOFF, "handoff_to"),
    ("report", STEP_MODEL, "report"),
    ("report", STEP_TOOL, "read_metrics"),
    ("report", STEP_MODEL, "report"),
    ("report", STEP_TOOL, "save_report"),
    ("report", STEP_MODEL, "report"),
    ("supervisor", STEP_MODEL, "supervisor"),
    ("supervisor", STEP_TOOL, "finish_run"),
]

# Model turns are `running` while the agent keeps calling tools and `done` when
# it answers; every tool/handoff step is `done`.
HAPPY_PATH_STATUSES = [
    "running", "done", "running", "done", "running", "done", "done",
    "running", "done", "running", "done", "running", "done", "done",
    "running", "done", "running", "done", "done",
    "running", "done", "running", "done", "running", "done", "done",
    "running", "done", "running", "done", "running", "done", "done",
    "running", "done",
]


class ScriptedChatModel(BaseChatModel):
    """A `BaseChatModel` that answers with one scripted message per call.

    It records every dialogue it was asked to answer, so a test can prove the
    exact order of model calls without any network access. It also records every
    tool binding: a model that never receives its tools cannot call them.
    """

    script: list[AIMessage]
    index: int = 0
    failure: Any = None
    calls: ClassVar[list[list[BaseMessage]]] = []
    bound_tools: ClassVar[list[tuple[str, ...]]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-seo-agent"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        self.bound_tools.append(tuple(getattr(tool, "name", str(tool)) for tool in tools))
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if self.failure is not None:
            raise self.failure
        assert self.script, "unexpected model call"
        # The last scripted answer repeats, so a test that only wants a fixed
        # turn (a plain answer, or an idle supervisor) needs no padding.
        index = min(self.index, len(self.script) - 1)
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=self.script[index])])


@dataclass
class Harness:
    """One run: a real repository, a real toolbox, and the scripted model."""

    repository: SeoRepository
    input: SeoInput
    analysis_id: str
    model: ScriptedChatModel
    config_dir: Path
    connections: ConnectionService
    fetcher: FakeSiteFetcher = field(default_factory=FakeSiteFetcher)
    gateway: ScriptedSeoGateway = field(default_factory=lambda: ScriptedSeoGateway(DOCUMENTS))
    factory: SeoProviderFactorySpy = field(default_factory=SeoProviderFactorySpy)
    toolboxes: list[SeoToolbox] = field(default_factory=list)

    def toolbox_factory(self, analysis_id: str, input: SeoInput, budget: SeoBudget) -> SeoToolbox:
        toolbox = SeoToolbox(
            self.repository,
            self.fetcher,
            self.gateway,
            self.connections,
            self.factory,
            analysis_id=analysis_id,
            input=input,
            connection_ids=input.connection_ids,
            budget=budget,
            poll_interval=0.0,
            model_name="seo-model",
        )
        self.toolboxes.append(toolbox)
        return toolbox

    def runtime(self, **overrides: Any) -> SeoAgentRuntime:
        options: dict[str, Any] = {"checkpointer": checkpoint_factory(self.config_dir)}
        options.update(overrides)
        return SeoAgentRuntime(self.repository, self.toolbox_factory, self.model, **options)

    def trace(self) -> list[dict]:
        return self.repository.trace_page(self.analysis_id)["items"]


def checkpoint_factory(config_dir: Path):
    """A factory of owner-only SQLite checkpointers inside the temporary dir."""

    @asynccontextmanager
    async def open_checkpointer(_analysis_id: str):
        path = checkpoint_path(config_dir)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            if path.exists():
                path.chmod(CHECKPOINT_FILE_MODE)
            yield saver

    return open_checkpointer


def make_harness(tmp_path: Path, connection_repository, settings, script=None) -> Harness:
    repository = SeoRepository(tmp_path)
    repository.initialize()
    connections = ConnectionService(connection_repository, settings)
    connections.save({"api_key": "key-1"}, CONNECTION_ID)
    request = normalize_seo_request(payload())
    analysis_id = repository.create_analysis(
        request,
        {"search_upper": 43, "model_upper": 40, "generated_limit": 40, "connections": 1},
    )
    # The recorder lists are class attributes, so one harness starts clean and a
    # test never depends on which test ran before it.
    ScriptedChatModel.calls.clear()
    ScriptedChatModel.bound_tools.clear()
    return Harness(
        repository=repository,
        input=request,
        analysis_id=analysis_id,
        model=ScriptedChatModel(script=happy_path_script() if script is None else script),
        config_dir=tmp_path,
        connections=connections,
    )


# -- the bridge --------------------------------------------------------------


def _resolve(schema: dict, root: dict) -> dict:
    """Inline one `$ref` of a pydantic model schema, so an assertion can read it."""
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = root["$defs"][name]
    return schema


@pytest.mark.anyio
async def test_bridge_tools_mirror_the_declared_schemas_of_every_agent(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)
    toolbox = harness.toolbox_factory(
        harness.analysis_id, harness.input, SeoBudget.for_connections(1),
    )

    for agent in ("supervisor", *SPECIALISTS):
        tools = langchain_tools(toolbox, agent)
        assert [tool.name for tool in tools] == [schema.name for schema in toolbox.schemas_for(agent)]
        for tool in tools:
            root = tool.args_schema.model_json_schema()
            specs = TOOL_ARGUMENTS[tool.name]
            assert root["additionalProperties"] is False
            assert set(root["properties"]) == {spec.name for spec in specs}
            assert set(root.get("required", [])) == {spec.name for spec in specs if spec.required}
        if agent == "site":
            bound = _resolve(
                next(tool for tool in tools if tool.name == "fetch_site")
                .args_schema.model_json_schema()["properties"]["max_pages"],
                next(tool for tool in tools if tool.name == "fetch_site").args_schema.model_json_schema(),
            )
            assert (bound["minimum"], bound["maximum"]) == (1, 20)
        if agent == "queries":
            root = next(tool for tool in tools if tool.name == "save_queries").args_schema.model_json_schema()
            items = root["properties"]["queries"]
            assert (items["minItems"], items["maxItems"]) == (1, 40)
            item = _resolve(items["items"], root)
            assert item["additionalProperties"] is False
            assert set(item["properties"]) == {"query", "category", "service"}
            assert set(item["required"]) == {"query", "category"}
        if agent == "competitors":
            root = next(tool for tool in tools if tool.name == "save_candidates").args_schema.model_json_schema()
            item = _resolve(root["properties"]["candidates"]["items"], root)
            assert item["additionalProperties"] is False
            assert set(item["properties"]) == {"host", "note"}
            assert item["required"] == ["host"]


# -- the happy path ----------------------------------------------------------


@pytest.mark.anyio
async def test_every_agent_binds_its_declared_tools(tmp_path, repository, settings):
    """A model that is never given its tools cannot call them.

    `create_agent` binds the tools of a specialist before calling it, and the
    supervisor needs its control tools just as much; the tracer in between must
    forward the binding instead of swallowing it.
    """
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    bound = {frozenset(names) for names in ScriptedChatModel.bound_tools}
    for agent, declared in AGENT_TOOLS.items():
        assert frozenset(declared) in bound, f"{agent} never received its tools"


@pytest.mark.anyio
async def test_the_tracer_forwards_bound_tools_and_still_traces():
    """The bound view keeps the trace hooks and hands the tools to the model."""

    class NamedTool:
        def __init__(self, name: str) -> None:
            self.name = name

    inner = ScriptedChatModel(script=[AIMessage(content="готово")])
    inner.bound_tools.clear()
    recorded: list[tuple[str, str]] = []
    tracer = ModelTracer(
        model=inner,
        agent="supervisor",
        recorder=lambda agent, status: recorded.append((agent, status)),
        should_stop=lambda: False,
    )

    bound = tracer.bind_tools([NamedTool("handoff_to"), NamedTool("finish_run")])
    assert bound is not tracer
    answer = await bound.ainvoke([HumanMessage("передай работу агенту сайта")])

    assert answer.content == "готово"
    assert inner.bound_tools == [("handoff_to", "finish_run")]
    assert recorded == [("supervisor", "done")]
    # The unbound tracer stays unbound: only the clone carries the tools.
    assert tracer.bound is None


@pytest.mark.anyio
async def test_a_transport_failure_is_stored_with_its_safe_provider_message(
    tmp_path, repository, settings,
):
    """A refused connection must not be reported as an unknown supervisor error."""
    harness = make_harness(tmp_path, repository, settings)
    harness.model.failure = ProviderError(CONNECTION_ERROR)

    await harness.runtime().run(harness.analysis_id, harness.input)

    agents = {entry["agent"]: entry for entry in harness.repository.agents(harness.analysis_id)}
    assert agents["supervisor"]["status"] == "error"
    assert agents["supervisor"]["error"] == CONNECTION_ERROR
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "failed"


@pytest.mark.anyio
async def test_happy_path_runs_every_agent_and_completes_the_analysis(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    assert harness.model.index == len(happy_path_script())
    assert len(harness.model.calls) == len(happy_path_script())
    statuses = {
        entry["agent"]: entry["status"] for entry in harness.repository.agents(harness.analysis_id)
    }
    # `save_*` marks its own agent `done`; a running checks agent is closed as
    # `done` when the supervisor moves on to the report; the supervisor itself
    # gets a terminal status when the run is published.
    assert statuses == {
        "supervisor": "done",
        "site": "done",
        "competitors": "done",
        "queries": "done",
        "checks": "done",
        "report": "done",
    }
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "completed"
    assert harness.repository.snapshot(harness.analysis_id)["budget_exhausted"] is False

    trace = [(item["agent"], item["kind"], item["name"]) for item in harness.trace()]
    assert trace == HAPPY_PATH_TRACE
    assert [item["step_index"] for item in harness.trace()] == list(range(1, len(trace) + 1))
    assert [item["status"] for item in harness.trace()] == HAPPY_PATH_STATUSES


@pytest.mark.anyio
async def test_model_steps_record_only_the_agent_and_the_turn_status(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    steps = [item for item in harness.trace() if item["kind"] == STEP_MODEL]
    assert len(steps) == 20
    assert [item["status"] for item in steps] == [
        status
        for (agent, kind, _name), status in zip(HAPPY_PATH_TRACE, HAPPY_PATH_STATUSES, strict=True)
        if kind == STEP_MODEL
    ]
    assert all(item["result_summary"] is None for item in steps)
    assert all(item["arguments"] == {} for item in steps)
    dumped = json.dumps(steps, ensure_ascii=False)
    assert "Ромашка" not in dumped
    assert "купить букет" not in dumped


@pytest.mark.anyio
async def test_saved_rows_reach_the_repository_and_the_paid_calls_stay_inside_the_budget(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    snapshot = harness.repository.snapshot(harness.analysis_id)
    assert [page["url"] for page in snapshot["pages"]] == [DEFAULT_SEO_PAGE.url]
    assert snapshot["company_name"] == "Ромашка"
    assert set(snapshot["services"]) == {"Букеты", "Доставка", "Свадьбы"}
    assert [candidate["host"] for candidate in snapshot["candidates"]] == ["rival.ru"]
    assert [query["text"] for query in snapshot["queries"]] == [
        item["query"] for item in ANALYSIS_QUERIES
    ]
    assert snapshot["conclusions"]["summary"] == SUMMARY
    assert snapshot["conclusions"]["recommendations"] == RECOMMENDATIONS
    assert snapshot["conclusions"]["model"] == "seo-model"

    # One paid key search plus five generated searches, and five model answers.
    # Tool batches run concurrently, so only the sets are ordered by contract.
    assert sorted(harness.gateway.submitted) == sorted(
        [(SEEDS[0], 225)] + [(item["query"], 225) for item in ANALYSIS_QUERIES],
    )
    assert sorted(harness.factory.calls) == sorted(
        (CONNECTION_ID, item["query"]) for item in ANALYSIS_QUERIES
    )

    budget = harness.repository.budget_state(harness.analysis_id)
    assert budget["pages"] == 1
    assert budget["seed_searches"] == 1
    assert budget["searches"] == 5
    assert budget["model_rows"] == 5
    assert budget["handoffs"] == 5


@pytest.mark.anyio
async def test_finish_run_only_flags_the_end_and_the_runtime_completes_the_analysis(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    toolbox = harness.toolboxes[-1]
    # `finish_run` belongs to the toolbox: it flags the end and never finalizes.
    assert toolbox.finished is True
    assert toolbox.finish_reason == FINISH_REASON
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "completed"


@pytest.mark.anyio
async def test_supervisor_turn_backstop_publishes_the_run_as_stopped_by_the_limit(
    tmp_path, repository, settings,
):
    harness = make_harness(
        tmp_path, repository, settings, script=[AIMessage(content="Пока ничего")],
    )

    await harness.runtime(max_supervisor_turns=2).run(harness.analysis_id, harness.input)

    snapshot = harness.repository.snapshot(harness.analysis_id)
    # A supervisor that never reaches a handoff burns its turn budget: the run is
    # published from the stored rows (here: nothing was collected) and flagged.
    assert snapshot["status"] == "completed"
    assert snapshot["budget_exhausted"] is True
    statuses = {
        entry["agent"]: entry["status"] for entry in harness.repository.agents(harness.analysis_id)
    }
    assert statuses["supervisor"] == "done"
    assert all(statuses[agent] == "skipped" for agent in SPECIALISTS)
    assert harness.model.index == 2


@pytest.mark.anyio
async def test_specialist_turn_budget_stops_the_run_with_the_limit_flag(
    tmp_path, repository, settings,
):
    endless = [call("handoff_to", agent="site", reason="Собрать сведения")]
    endless += [call("fetch_site", max_pages=1) for _ in range(MAX_SPECIALIST_TURNS + 2)]
    harness = make_harness(tmp_path, repository, settings, script=endless)

    await harness.runtime().run(harness.analysis_id, harness.input)

    snapshot = harness.repository.snapshot(harness.analysis_id)
    assert snapshot["status"] == "completed"
    assert snapshot["budget_exhausted"] is True
    # One supervisor turn plus exactly the specialist cap: the over-limit turn is
    # refused before the paid model call is made.
    assert harness.model.index == MAX_SPECIALIST_TURNS + 1


@pytest.mark.anyio
async def test_a_run_without_site_facts_fails_before_it_can_publish_a_report(
    tmp_path, repository, settings,
):
    script = [
        call("handoff_to", agent="site", reason="Собрать сведения"),
        call("fetch_site", max_pages=1),
        # `save_site_facts` is refused: the crawl found no page to base facts on.
        call("save_site_facts", company_name="Ромашка", services=["Букеты"]),
        AIMessage(content="Не удалось сохранить сведения"),
        # The supervisor gives up early instead of looping: the run must not
        # pretend to have a report when the site facts are missing.
        call("finish_run", reason="Больше нечего делать"),
    ]
    harness = make_harness(tmp_path, repository, settings, script=script)
    harness.fetcher.pages = ()

    await harness.runtime().run(harness.analysis_id, harness.input)

    snapshot = harness.repository.snapshot(harness.analysis_id)
    assert snapshot["status"] == "failed"
    assert snapshot["budget_exhausted"] is False
    agents = {entry["agent"]: entry for entry in harness.repository.agents(harness.analysis_id)}
    assert agents["supervisor"]["status"] == "error"
    assert agents["supervisor"]["error"] is not None
    assert all(
        entry["status"] in {"done", "error", "skipped"} for entry in agents.values()
    )


# -- checkpointing and containment -------------------------------------------


@pytest.mark.anyio
async def test_checkpoint_is_owner_only_and_a_second_graph_sees_the_finished_state(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    await harness.runtime().run(harness.analysis_id, harness.input)

    path = checkpoint_path(tmp_path)
    assert path.name == CHECKPOINT_FILE_NAME
    assert path.exists()
    assert path.stat().st_mode & 0o777 == CHECKPOINT_FILE_MODE

    # A second graph over the same checkpoint file reads the finished run without
    # a single further model call.
    reader = ScriptedChatModel(script=[])
    toolbox = harness.toolbox_factory(harness.analysis_id, harness.input, SeoBudget.for_connections(1))
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_agent_graph(reader, toolbox, checkpointer=saver)
        state = await graph.aget_state({"configurable": {"thread_id": harness.analysis_id}})

    assert state.values["finished"] is True
    assert state.values["finish_reason"] == FINISH_REASON
    assert state.values["specialists"] == {
        "supervisor": 6, "site": 1, "competitors": 1, "queries": 1, "checks": 1, "report": 1,
    }
    assert reader.index == 0


@pytest.mark.anyio
async def test_runtime_contains_a_failing_model_as_a_safe_supervisor_error(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings, script=[])

    await harness.runtime().run(harness.analysis_id, harness.input)

    agents = {entry["agent"]: entry for entry in harness.repository.agents(harness.analysis_id)}
    assert agents["supervisor"]["status"] == "error"
    assert agents["supervisor"]["error"] is not None
    assert "unexpected model call" not in agents["supervisor"]["error"]
    # An unexpected model failure fails this run with a safe message and leaves
    # no agent open; the raw exception text never reaches the stored error.
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "failed"
    assert all(
        entry["status"] in {"done", "error", "skipped"} for entry in agents.values()
    )


@pytest.mark.anyio
async def test_the_run_is_an_awaitable_task_that_never_raises(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)

    task = asyncio.create_task(harness.runtime().run(harness.analysis_id, harness.input))
    await task

    assert task.exception() is None


# -- cancellation ------------------------------------------------------------


@pytest.mark.anyio
async def test_cancelling_a_live_run_stops_every_paid_call_and_keeps_the_status(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)
    runtime = harness.runtime()
    original = harness.model._generate

    def cancel_after_the_first_turn(messages, stop=None, run_manager=None, **kwargs):
        result = original(messages, stop=stop, run_manager=run_manager, **kwargs)
        # The supervisor has just asked for the first handoff: from here on no
        # tool of the site agent and no further model turn may be paid for.
        runtime.cancel(harness.analysis_id)
        return result

    harness.model._generate = cancel_after_the_first_turn  # type: ignore[method-assign]

    await runtime.run(harness.analysis_id, harness.input)

    snapshot = harness.repository.snapshot(harness.analysis_id)
    assert snapshot["status"] == "cancelled"
    assert snapshot["budget_exhausted"] is False
    assert harness.gateway.submitted == []
    assert harness.factory.calls == []
    assert harness.model.index == 1
    statuses = {
        entry["agent"]: entry["status"] for entry in harness.repository.agents(harness.analysis_id)
    }
    assert all(status in {"done", "error", "skipped"} for status in statuses.values())
    assert harness.trace(), "the trace of the cancelled run is kept"
    assert checkpoint_path(tmp_path).exists()

    # A repeated cancel, and a cancel of an already finished run, stay safe.
    runtime.cancel(harness.analysis_id)
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "cancelled"


# -- resume after a restart --------------------------------------------------


@pytest.mark.anyio
async def test_resume_continues_from_the_checkpoint_and_never_repeats_stored_work(
    tmp_path, repository, settings,
):
    # First process: it crawls the site, then dies mid-run (the finalization
    # never happens, which is exactly what a restart leaves behind).
    dying = make_harness(tmp_path, repository, settings)
    crashed = dying.runtime(recursion_limit=8)
    crashed._mark_error = lambda *args, **kwargs: None  # type: ignore[method-assign]

    await crashed.run(dying.analysis_id, dying.input)

    assert dying.repository.snapshot(dying.analysis_id)["status"] == "running"
    assert dying.repository.snapshot(dying.analysis_id)["pages"], "the crawl was stored"

    # Second process: a new runtime, a fresh toolbox, the same config directory.
    resumed = make_harness(tmp_path, repository, settings, script=happy_path_script()[4:])
    assert await resumed.runtime().resume(dying.analysis_id) is True

    snapshot = dying.repository.snapshot(dying.analysis_id)
    assert snapshot["status"] == "completed"
    # The site agent is not visited again: the pages come from the database.
    assert resumed.fetcher.hosts == []
    assert [page["url"] for page in snapshot["pages"]] == [DEFAULT_SEO_PAGE.url]
    assert snapshot["company_name"] == "Ромашка"
    assert snapshot["conclusions"]["summary"] == SUMMARY


@pytest.mark.anyio
async def test_resume_without_a_checkpoint_reports_that_nothing_can_be_resumed(
    tmp_path, repository, settings,
):
    harness = make_harness(tmp_path, repository, settings)
    runtime = harness.runtime()
    baseline = len(harness.model.calls)

    assert await runtime.resume(harness.analysis_id) is False
    assert harness.repository.snapshot(harness.analysis_id)["status"] == "running"
    assert len(harness.model.calls) == baseline
