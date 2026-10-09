"""Pure rules of the server-owned SEO agent tools: budgets, schemas, and arguments.

Agents decide *what* to do; this module decides *what is allowed*. It owns the
per-run budget counters with their hard caps, the JSON schema of every tool, the
per-agent tool subsets, and the argument validator. Nothing here performs I/O and
nothing here trusts the model: an unknown tool, an extra field, a wrong type, or
an exhausted budget becomes a safe `ToolRejected`/`BudgetExceeded` that the
toolbox returns to the model instead of executing.

The limits are the agreed ceilings of one run: 5 fetched pages (owned by
`domain.site_fetch`), 5 paid Yandex searches (the three key ones plus the two
generated ones), 5 model answers for the whole run, 15 supervisor handoffs, 20
model turns per specialist, 120 tool calls, and 120 seconds per LLM call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.core.errors import AppError
from app.domain.seo import (
    AGENTS,
    GENERATED_QUERY_LIMIT,
    MAX_CONNECTIONS,
    MAX_QUERY_LENGTH,
    MAX_QUERY_WORDS,
    MAX_SERVICE_LENGTH,
    MAX_SERVICES,
    MIN_GENERATED_QUERIES,
    QUERY_CATEGORIES,
    SEED_COUNT,
)
from app.domain.seo_llm import ToolSchema
from app.domain.site_fetch import MAX_FETCH_PAGES

# Budget ceilings of one run. `MAX_FETCH_PAGES` is re-exported so a caller reads
# every cap from one module. The Yandex pool is derived from the fixed query
# shape, so the three key searches and the generated ones can never drift apart,
# and the model-answer cap is flat: five paid answers per run, not per
# connection, so adding a connection never raises the price of the run.
MAX_SEARCH_REQUESTS = SEED_COUNT + GENERATED_QUERY_LIMIT
MAX_MODEL_ANSWERS = 5
MAX_SUPERVISOR_HANDOFFS = 15
MAX_SPECIALIST_TURNS = 20
MAX_TOOL_CALLS = 120
LLM_CALL_TIMEOUT = 120.0

# The only region of this version: the whole of Russia.
SEARCH_REGION = 225

# Argument bounds: they keep a single trace entry and a single prompt small.
MAX_COMPANY_NAME_LENGTH = 200
MAX_REASON_LENGTH = 500
MAX_NOTE_LENGTH = 300
MAX_URL_ARGUMENT_LENGTH = 2048
MAX_CANDIDATE_ARGUMENTS = 40
MAX_CONNECTION_ID_LENGTH = 100
MAX_CATEGORY_ARGUMENT = 40

UNKNOWN_TOOL = "Неизвестный инструмент"
TOOL_NOT_ALLOWED = "Инструмент недоступен этому агенту"
INVALID_ARGUMENTS = "Недопустимые аргументы инструмента"
INVALID_AGENT = "Неизвестный агент SEO-анализа"
INVALID_QUERY = (
    f"Запрос должен содержать от 1 до {MAX_QUERY_LENGTH} символов и не более {MAX_QUERY_WORDS} слов"
)
BUDGET_EXHAUSTED = "Лимит прогона исчерпан"
SUPERVISOR_ONLY = "Инструмент доступен только супервизору"
CANCELLED = "Прогон отменён"
FATAL_SITE_UNREACHABLE = "Сайт недоступен: не удалось прочитать ни одной страницы"

# The tools that spend real money at Yandex or at a model provider. A run whose
# site can never be read is already lost (its facts, and therefore its queries,
# can never exist), so the first of these calls stops it instead of paying.
PAID_TOOLS = frozenset({"yandex_search", "search_many", "ask_models"})
# Failed crawls of one run before the site counts as unreachable: one network
# blip is still retried, an unreachable host is not paid for twice.
SITE_FAILURE_LIMIT = 2

# `AGENTS` is imported from `domain.seo`, the single source of the vocabulary;
# the specialists are the same tuple without the supervisor.
SPECIALIST_AGENTS = AGENTS[1:]


class ToolRejected(AppError):
    """A safe refusal: the model gets it as the tool result, never as a crash."""


class BudgetExceeded(AppError):
    """A hard run budget is used up; the model gets a safe refusal."""


class SeoCancelled(AppError):
    """The user cancelled the run: stop it before any further paid call.

    Cancellation is not a tool result and not a model-visible refusal: it leaves
    the graph and is handled by `SeoAgentRuntime`, which keeps the stored rows
    and the trace and leaves the analysis in its `cancelled` state.
    """


class SeoFatal(AppError):
    """A fatal run condition: stop the graph before any further paid call.

    Like cancellation it is not a tool result: it leaves the graph, and
    `SeoAgentRuntime` fails the analysis with this fixed safe message. The
    trigger is a state the run can never recover from — currently a site that
    answered no page at all, which makes the site facts and the queries
    impossible.
    """


@dataclass(frozen=True, kw_only=True)
class SeoBudget:
    """Immutable usage counters of one run: every spend returns a new budget.

    A `spend_*` call either returns the incremented copy or raises
    `BudgetExceeded`; it never mutates the receiver, so a caller can hold the
    spent budget of a finished step while another spends the next one.
    """

    pages: int = 0
    searches: int = 0
    model_answers: int = 0
    tool_calls: int = 0
    handoffs: int = 0
    turns: tuple[tuple[str, int], ...] = ()

    max_pages: int = MAX_FETCH_PAGES
    max_searches: int = MAX_SEARCH_REQUESTS
    max_model_answers: int = MAX_MODEL_ANSWERS
    max_tool_calls: int = MAX_TOOL_CALLS
    max_handoffs: int = MAX_SUPERVISOR_HANDOFFS
    max_turns: int = MAX_SPECIALIST_TURNS

    @classmethod
    def for_run(cls) -> SeoBudget:
        """Build the budget of one run: no cap depends on the connection count."""
        return cls()

    def turns_for(self, agent: str) -> int:
        """Return the model turns one specialist already spent."""
        for name, count in self.turns:
            if name == agent:
                return count
        return 0

    def spend_pages(self, count: int = 1) -> SeoBudget:
        return self._spend("pages", self.max_pages, count)

    def spend_search(self, count: int = 1) -> SeoBudget:
        return self._spend("searches", self.max_searches, count)

    def spend_model_answer(self, count: int = 1) -> SeoBudget:
        return self._spend("model_answers", self.max_model_answers, count)

    def spend_tool_call(self, count: int = 1) -> SeoBudget:
        return self._spend("tool_calls", self.max_tool_calls, count)

    def spend_handoff(self, count: int = 1) -> SeoBudget:
        return self._spend("handoffs", self.max_handoffs, count)

    def spend_turn(self, agent: str, count: int = 1) -> SeoBudget:
        """Spend one model turn of one specialist; its own cap is `max_turns`."""
        if agent not in SPECIALIST_AGENTS:
            raise ToolRejected(INVALID_AGENT)
        used = self.turns_for(agent)
        if used + _require_count(count) > self.max_turns:
            raise BudgetExceeded(BUDGET_EXHAUSTED)
        turns = tuple((name, used + count if name == agent else spent) for name, spent in self.turns)
        if not any(name == agent for name, _ in self.turns):
            turns = (*self.turns, (agent, count))
        return replace(self, turns=turns)

    def as_dict(self) -> dict[str, object]:
        """Return the used-versus-cap summary the tools report to the model."""
        return {
            "pages": {"used": self.pages, "cap": self.max_pages},
            "searches": {"used": self.searches, "cap": self.max_searches},
            "model_answers": {"used": self.model_answers, "cap": self.max_model_answers},
            "tool_calls": {"used": self.tool_calls, "cap": self.max_tool_calls},
            "handoffs": {"used": self.handoffs, "cap": self.max_handoffs},
            "turns": {
                agent: {"used": self.turns_for(agent), "cap": self.max_turns}
                for agent, _ in self.turns
            },
        }

    def _spend(self, field: str, cap: int, count: int) -> SeoBudget:
        used = getattr(self, field)
        if used + _require_count(count) > cap:
            raise BudgetExceeded(BUDGET_EXHAUSTED)
        return replace(self, **{field: used + count})


def _require_count(count: object) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ToolRejected(INVALID_ARGUMENTS)
    return count


ArgumentKind = Literal[
    "text",
    "optional_text",
    "integer",
    "query",
    "query_list",
    "query_objects",
    "candidate_list",
    "connection_list",
    "services",
]


@dataclass(frozen=True)
class ArgumentSpec:
    """One declared argument of one tool: its kind and its bound."""

    name: str
    kind: ArgumentKind
    maximum: int
    required: bool = False
    description: str = ""


def _arg(
    name: str, kind: ArgumentKind, maximum: int, description: str, *, required: bool = False,
) -> ArgumentSpec:
    return ArgumentSpec(name=name, kind=kind, maximum=maximum, required=required, description=description)


TOOL_DESCRIPTIONS: Mapping[str, str] = {
    "fetch_site": (
        "Обойти страницы введённого сайта и его поддоменов. Возвращает прочитанные страницы "
        "с длиной текста; обходятся только страницы этого сайта."
    ),
    "read_page": "Прочитать одну страницу введённого сайта и получить её заголовок и начало текста.",
    "save_site_facts": (
        "Сохранить название компании и услуги, найденные на сайте. Требует хотя бы одной "
        "прочитанной страницы; услуги объединяются с введёнными."
    ),
    "yandex_search": (
        "Проверить один запрос в Яндексе по всей России (регион 225). Повторный вызов по тому же "
        "запросу возвращает сохранённый результат без нового обращения."
    ),
    "list_seed_results": "Показать сохранённые выдачи по трём ключевым запросам. Внешних вызовов нет.",
    "save_candidates": (
        "Сохранить выбранных конкурентов: передайте только хосты и заметки. Числа (повторяемость, "
        "средняя позиция) сервер считает сам по сохранённым ключевым выдачам."
    ),
    "read_facts": "Показать сохранённые название компании, услуги и прочитанные страницы.",
    "save_queries": (
        f"Сохранить от {MIN_GENERATED_QUERIES} до {GENERATED_QUERY_LIMIT} уникальных сгенерированных "
        "запросов с категориями и услугами. Требует сохранённых сведений о сайте."
    ),
    "search_many": (
        "Проверить пачку сохранённых сгенерированных запросов в Яндексе (регион 225). Без списка "
        "проверяются все сохранённые запросы; уже проверенные повторно не оплачиваются."
    ),
    "ask_models": (
        "Опросить выбранные модели по сохранённым запросам. Уже проверенные пары возвращаются "
        "без нового обращения; ошибка одного подключения не мешает остальным. За весь прогон "
        f"оплачивается не больше {MAX_MODEL_ANSWERS} ответов: пары сверх лимита не оплачиваются."
    ),
    "read_checks": "Показать состояние поисковых и модельных проверок и безопасные тексты ошибок.",
    "handoff_to": "Передать управление специалисту. Доступно только супервизору.",
    "finish_run": "Завершить прогон. Доступно только супервизору.",
    "read_status": "Показать состояния агентов, израсходованный бюджет и готовность данных.",
}

TOOL_ARGUMENTS: Mapping[str, tuple[ArgumentSpec, ...]] = {
    "fetch_site": (
        _arg("max_pages", "integer", MAX_FETCH_PAGES, "Сколько страниц прочитать за этот вызов."),
    ),
    "read_page": (
        _arg("url", "text", MAX_URL_ARGUMENT_LENGTH, "Адрес страницы введённого сайта.", required=True),
    ),
    "save_site_facts": (
        _arg("company_name", "optional_text", MAX_COMPANY_NAME_LENGTH,
             "Название компании или пустая строка.", required=True),
        _arg("services", "services", MAX_SERVICES,
             "Услуги, найденные на сайте; пустой список, если их нет.", required=True),
    ),
    "yandex_search": (
        _arg("query", "query", MAX_QUERY_LENGTH,
             "Ключевой или сохранённый сгенерированный запрос.", required=True),
    ),
    "list_seed_results": (),
    "save_candidates": (
        _arg("candidates", "candidate_list", MAX_CANDIDATE_ARGUMENTS,
             "Выбранные конкуренты: хосты и короткие заметки. Пустой список — «конкурентов нет».",
             required=True),
    ),
    "read_facts": (),
    "save_queries": (
        _arg("queries", "query_objects", GENERATED_QUERY_LIMIT,
             "Запросы с категорией commercial|informational|comparative и услугой.", required=True),
    ),
    "search_many": (
        _arg("queries", "query_list", GENERATED_QUERY_LIMIT,
             "Тексты сохранённых запросов; без поля проверяются все сохранённые."),
    ),
    "ask_models": (
        _arg("queries", "query_list", GENERATED_QUERY_LIMIT,
             "Тексты сохранённых запросов; без поля проверяются все сохранённые."),
        _arg("connection_ids", "connection_list", MAX_CONNECTIONS,
             "Выбранные подключения моделей; без поля используются все подключения прогона."),
    ),
    "read_checks": (),
    "handoff_to": (
        _arg("agent", "text", 32, "Имя специалиста: site, competitors, queries, checks.",
             required=True),
        _arg("reason", "optional_text", MAX_REASON_LENGTH, "Короткая причина передачи.", required=True),
    ),
    "finish_run": (
        _arg("reason", "optional_text", MAX_REASON_LENGTH, "Короткая причина завершения."),
    ),
    "read_status": (),
}

SITE_TOOLS = ("fetch_site", "read_page", "save_site_facts")
COMPETITOR_TOOLS = ("yandex_search", "list_seed_results", "save_candidates")
QUERY_TOOLS = ("read_facts", "save_queries")
CHECK_TOOLS = ("search_many", "ask_models", "read_checks")
SUPERVISOR_TOOLS = ("handoff_to", "finish_run", "read_status")
AGENT_TOOLS: Mapping[str, tuple[str, ...]] = {
    "supervisor": SUPERVISOR_TOOLS,
    "site": SITE_TOOLS,
    "competitors": COMPETITOR_TOOLS,
    "queries": QUERY_TOOLS,
    "checks": CHECK_TOOLS,
}


def schema_for(name: str) -> ToolSchema:
    """Build one tool schema from its declared arguments, or refuse an unknown name."""
    arguments = TOOL_ARGUMENTS.get(name)
    if arguments is None:
        raise ToolRejected(UNKNOWN_TOOL)
    properties = {argument.name: _json_schema(argument) for argument in arguments}
    required = [argument.name for argument in arguments if argument.required]
    parameters: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required
    return ToolSchema(name=name, description=TOOL_DESCRIPTIONS[name], parameters=parameters)



def tools_for(agent: str) -> tuple[ToolSchema, ...]:
    """Return the tools one agent may see; an unknown agent is refused."""
    names = AGENT_TOOLS.get(agent)
    if names is None:
        raise ToolRejected(INVALID_AGENT)
    return tuple(TOOL_SCHEMAS[name] for name in names)


def validate_arguments(name: str, arguments: object) -> dict[str, object]:
    """Validate one tool call and return its normalized arguments.

    Unknown tools, missing required fields, extra fields, wrong types, empty
    strings, and values outside the documented bounds raise `ToolRejected` with a
    fixed Russian message; the model-provided value is never echoed back.
    """
    specs = TOOL_ARGUMENTS.get(name)
    if specs is None:
        raise ToolRejected(UNKNOWN_TOOL)
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, Mapping):
        raise ToolRejected(INVALID_ARGUMENTS)
    if any(not isinstance(key, str) for key in arguments):
        raise ToolRejected(INVALID_ARGUMENTS)
    known = {spec.name for spec in specs}
    if not set(arguments) <= known:
        raise ToolRejected(INVALID_ARGUMENTS)
    if {spec.name for spec in specs if spec.required} - set(arguments):
        raise ToolRejected(INVALID_ARGUMENTS)
    return {
        spec.name: _validate_value(spec, arguments[spec.name])
        for spec in specs
        if spec.name in arguments
    }


def _validate_value(spec: ArgumentSpec, value: object) -> object:
    if spec.kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= spec.maximum:
            raise ToolRejected(INVALID_ARGUMENTS)
        return value
    if spec.kind == "text":
        text = _text(value, spec.maximum, allow_empty=False)
        return text
    if spec.kind == "optional_text":
        return _text(value, spec.maximum, allow_empty=True)
    if spec.kind == "query":
        return _query_text(value)
    if spec.kind == "query_list":
        return _query_list(value, spec.maximum)
    if spec.kind == "services":
        return _services(value, spec.maximum)
    if spec.kind == "connection_list":
        return _connection_list(value, spec.maximum)
    if spec.kind == "candidate_list":
        return _candidates(value, spec.maximum)
    return _query_objects(value, spec.maximum)


def _text(value: object, maximum: int, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ToolRejected(INVALID_ARGUMENTS)
    text = value.strip()
    if (not text and not allow_empty) or len(text) > maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    return text


def _query_text(value: object) -> str:
    if not isinstance(value, str):
        raise ToolRejected(INVALID_ARGUMENTS)
    text = value.strip()
    if not text or len(text) > MAX_QUERY_LENGTH or len(text.split()) > MAX_QUERY_WORDS:
        raise ToolRejected(INVALID_QUERY)
    return text


def _query_list(value: object, maximum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not 1 <= len(value) <= maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    return [_query_text(item) for item in value]


def _services(value: object, maximum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    services: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolRejected(INVALID_ARGUMENTS)
        text = item.strip()
        if not text or len(text) > MAX_SERVICE_LENGTH:
            raise ToolRejected(INVALID_ARGUMENTS)
        services.append(text)
    return services


def _connection_list(value: object, maximum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not 1 <= len(value) <= maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ToolRejected(INVALID_ARGUMENTS)
        text = item.strip()
        if not text or len(text) > MAX_CONNECTION_ID_LENGTH or text in ids:
            raise ToolRejected(INVALID_ARGUMENTS)
        ids.append(text)
    return ids


def _candidates(value: object, maximum: int) -> list[dict[str, str]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or not set(item) <= {"host", "note"} or "host" not in item:
            raise ToolRejected(INVALID_ARGUMENTS)
        host = _text(item["host"], MAX_URL_ARGUMENT_LENGTH, allow_empty=False)
        note = _text(item.get("note", ""), MAX_NOTE_LENGTH, allow_empty=True)
        key = host.rstrip(".").lower().removeprefix("www.")
        if not key or key in seen:
            raise ToolRejected(INVALID_ARGUMENTS)
        seen.add(key)
        candidates.append({"host": host, "note": note})
    return candidates


def _query_objects(value: object, maximum: int) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not 1 <= len(value) <= maximum:
        raise ToolRejected(INVALID_ARGUMENTS)
    queries: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or not set(item) <= {"query", "category", "service"}:
            raise ToolRejected(INVALID_ARGUMENTS)
        if "query" not in item or "category" not in item:
            raise ToolRejected(INVALID_ARGUMENTS)
        # The category vocabulary itself belongs to `accept_generated_queries`:
        # this layer only refuses a structurally unusable list.
        category = _text(item["category"], MAX_CATEGORY_ARGUMENT, allow_empty=False)
        service = _text(item.get("service", ""), MAX_SERVICE_LENGTH, allow_empty=True)
        queries.append({"query": _query_text(item["query"]), "category": category, "service": service})
    return queries


def _json_schema(spec: ArgumentSpec) -> dict[str, object]:
    if spec.kind == "integer":
        schema: dict[str, object] = {"type": "integer", "minimum": 1, "maximum": spec.maximum}
    elif spec.kind == "text":
        schema = {"type": "string", "minLength": 1, "maxLength": spec.maximum}
    elif spec.kind == "optional_text":
        schema = {"type": "string", "maxLength": spec.maximum}
    elif spec.kind == "query":
        schema = {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_LENGTH}
    elif spec.kind == "query_list":
        schema = {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_LENGTH},
            "minItems": 1,
            "maxItems": spec.maximum,
        }
    elif spec.kind == "query_objects":
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_LENGTH},
                    "category": {"type": "string", "enum": list(QUERY_CATEGORIES)},
                    "service": {"type": "string", "maxLength": MAX_SERVICE_LENGTH},
                },
                "required": ["query", "category"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": spec.maximum,
        }
    elif spec.kind == "services":
        schema = {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_SERVICE_LENGTH},
            "maxItems": spec.maximum,
        }
    elif spec.kind == "connection_list":
        schema = {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_CONNECTION_ID_LENGTH},
            "minItems": 1,
            "maxItems": spec.maximum,
        }
    else:
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "minLength": 1, "maxLength": MAX_URL_ARGUMENT_LENGTH},
                    "note": {"type": "string", "maxLength": MAX_NOTE_LENGTH},
                },
                "required": ["host"],
                "additionalProperties": False,
            },
            "maxItems": spec.maximum,
        }
    description = spec.description
    return {**schema, "description": description} if description else schema


# Built after every schema helper is defined: the mapping is the provider-facing
# contract of the server-owned tools.
TOOL_SCHEMAS: Mapping[str, ToolSchema] = {name: schema_for(name) for name in TOOL_ARGUMENTS}

__all__ = [
    "AGENTS",
    "AGENT_TOOLS",
    "BUDGET_EXHAUSTED",
    "CANCELLED",
    "CHECK_TOOLS",
    "COMPETITOR_TOOLS",
    "FATAL_SITE_UNREACHABLE",
    "GENERATED_QUERY_LIMIT",
    "LLM_CALL_TIMEOUT",
    "MAX_FETCH_PAGES",
    "MAX_MODEL_ANSWERS",
    "MAX_SEARCH_REQUESTS",
    "MAX_SPECIALIST_TURNS",
    "MAX_SUPERVISOR_HANDOFFS",
    "MAX_TOOL_CALLS",
    "MIN_GENERATED_QUERIES",
    "PAID_TOOLS",
    "QUERY_TOOLS",
    "SEARCH_REGION",
    "SITE_FAILURE_LIMIT",
    "SITE_TOOLS",
    "SPECIALIST_AGENTS",
    "SUPERVISOR_ONLY",
    "SUPERVISOR_TOOLS",
    "TOOL_SCHEMAS",
    "BudgetExceeded",
    "SeoBudget",
    "SeoCancelled",
    "SeoFatal",
    "ToolRejected",
    "schema_for",
    "tools_for",
    "validate_arguments",
]
