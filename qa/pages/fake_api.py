"""A scripted stand-in for the Python API behind the chat screen.

The browser talks only to the SvelteKit BFF, and every BFF call the chat screen
makes is answered here through `page.route`. The fake owns just enough of the
dialogue to react to the service-LLM answer a check scripts with
`route_completion`: it keeps the draft, builds a proposal once the draft is
complete, and starts the run when a `confirm` answer arrives for an open
proposal. The branch order mirrors `app.service.chat`, because that order is the
safety property of the feature — an incomplete draft always asks, a confirmation
without a proposal never launches, and only a pending proposal funds a run.

Snapshots, trace pages and report rows are scripted resources, so the checks
observe the real components without a run, without Yandex and without a model
call. Nothing is written to `runs.sqlite3`: the whole resource lives in the
browser.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, Route

from pages.seo import AGENT_IDS

STAMP = "2026-10-07T10:00:00Z"

ANALYSIS_ID = "qa-chat-run"
CHAT_ID = "qa-chat-1"
MODEL_ID = "qa-service-connection"

SEEDS = ("букеты москва", "доставка цветов", "цветы с доставкой")
SERVICES = ("букеты",)

# The answer of the service LLM when the user has just described the task: the
# exact fields the brief's first message names. A check that scripts no answer of
# its own gets this one, so the first turn always reaches a proposal.
PROPOSAL_ANSWER = json.dumps(
    {
        "reply": "Собрал параметры.",
        "intent": "message",
        "params": {
            "url": "https://example.ru",
            "sphere": "доставка цветов",
            "seeds": list(SEEDS),
            "services": list(SERVICES),
        },
    },
    ensure_ascii=False,
)

PROPOSAL_HINT = "Проверьте параметры и подтвердите запуск словом «да»."
NOTHING_TO_RUN = "Сейчас нечего запускать: опишите, что нужно проверить."

# The fixed question of each collected field, in the order the backend asks them.
QUESTIONS = {
    "url": "Укажите адрес главной страницы сайта со схемой: например, https://example.ru.",
    "sphere": "Опишите сферу бизнеса: чем занимается компания?",
    "seeds": "Назовите 3 разных ключевых запроса: по ним ищутся конкуренты.",
    "services": "Перечислите услуги, которые нужно проверить: от одной до 5.",
}



def metric(denominator: int, successes: int, average: float | None = None) -> dict:
    """One share exactly as the backend computes it; an empty denominator is null."""
    return {
        "denominator": denominator,
        "successes": successes,
        "share": round(successes / denominator, 4) if denominator else None,
        "average_position": average,
    }


def completed_snapshot(analysis_id: str = ANALYSIS_ID) -> dict:
    """A finished agent run: the report and its server-computed metrics."""
    counts = {"queries": 3, "search_rows": 2, "model_rows": 2, "search_errors": 0, "model_errors": 0}
    ai_block = {
        "name": metric(2, 1),
        "host": metric(2, 1),
        "combined": metric(2, 1),
        "branded": {"name": metric(1, 1), "host": metric(1, 1), "combined": metric(1, 1)},
        "unbranded": {"name": metric(1, 0), "host": metric(1, 1), "combined": metric(1, 1)},
    }
    return {
        "id": analysis_id,
        "status": "completed",
        "created_at": STAMP,
        "updated_at": STAMP,
        "finished_at": STAMP,
        "input": {
            "url": "https://example.ru",
            "host": "example.ru",
            "sphere": "доставка цветов",
            "seeds": list(SEEDS),
            "services": list(SERVICES),
            "connection_ids": [MODEL_ID],
        },
        "estimate": {"search_upper": 5, "model_upper": 5, "generated_limit": 2, "connections": 1},
        "company_name": "Ромашка",
        "services": list(SERVICES),
        "pages": [],
        "stages": [
            {"stage": number, "status": "done", "error": None, "counters": {}, "updated_at": STAMP}
            for number in range(1, 7)
        ],
        "agents": [
            {"agent": agent, "status": "done", "error": None, "updated_at": STAMP}
            for agent in AGENT_IDS
        ],
        "budget": {
            "pages": {"used": 1, "limit": 5},
            "searches": {"used": 2, "limit": 5},
            "model_answers": {"used": 2, "limit": 5},
            "tool_calls": {"used": 6, "limit": 120},
            "handoffs": {"used": 1, "limit": 15},
            "seed_searches": 0,
            "model_rows": 2,
            "steps": 6,
            "agent_steps": {agent: 1 for agent in AGENT_IDS},
        },
        "budget_exhausted": False,
        "candidates": [],
        "queries": [
            {
                "index": index,
                "text": f"запрос {index + 1}",
                "category": "commercial",
                "service": "букеты",
                "flags": {
                    "mentions_company_name": False,
                    "mentions_company_host": False,
                    "mentions_candidate_host": False,
                    "branded": False,
                },
            }
            for index in range(3)
        ],
        "counters": counts,
        "readiness": {
            "report_ready": True,
            "summary_ready": True,
            "queries_ready": True,
            "has_submitted_search_rows": True,
            "has_unsubmitted_search_rows": False,
            "has_unfinished_model_rows": False,
            "search_rows": 2,
            "model_rows": 2,
        },
        "aggregates": {
            "site": {
                "search": {
                    "overall": metric(2, 1, 3),
                    "branded": metric(1, 1, 3),
                    "unbranded": metric(1, 0),
                },
                "ai": {MODEL_ID: ai_block},
            },
            "competitors": [],
            "categories": {
                "commercial": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(2, 1)}},
                "informational": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
                "comparative": {"search": metric(0, 0), "ai": {MODEL_ID: metric(0, 0)}},
            },
            "services": {"букеты": {"search": metric(2, 1, 3), "ai": {MODEL_ID: metric(2, 1)}}},
            "counts": counts,
        },
    }


class ChatApi:
    """The scripted BFF: chat turns, the paid-run decision, and the run resources.

    One instance serves one test. `install()` puts the two browser routes in
    place; the scripted answers and resources are set before the page is driven.
    """

    def __init__(self, page: Page, *, analysis_id: str = ANALYSIS_ID, chat_id: str = CHAT_ID) -> None:
        self.page = page
        self.analysis_id = analysis_id
        self.chat_id = chat_id
        self.answers: list[str] = []
        self.errors: dict[str, tuple[int, dict[str, Any]]] = {}
        self.snapshots: list[dict] = []
        self.trace_pages: dict[Any, dict] = {}
        self.row_pages: dict[tuple[Any, Any], dict] = {}
        self.cancel_snapshot: dict | None = None
        self.requests: list[str] = []
        self.trace_cursors: list[str | None] = []
        self.row_cursors: list[tuple[str | None, str | None]] = []
        self.cancel_body: str | None = None
        self.draft: dict[str, Any] = {"url": "", "sphere": "", "seeds": [], "services": []}
        self.pending = False
        self.seq = 0
        self.deleted = False
        self.chat: dict[str, Any] = self._summary("Новый чат")

    # -- the script --------------------------------------------------------

    def install(self) -> ChatApi:
        """Answer every chat and analysis call of the browser locally."""
        self.page.route("**/api/seo/chats**", self._route_chat)
        self.page.route("**/api/seo/analyses**", self._route_analysis)
        return self

    def route_completion(self, *, answer: str) -> ChatApi:
        """Queue the answer the service LLM gives to the next user message."""
        self.answers.append(answer)
        return self

    def route_error(self, path: str, *, status: int = 500, detail: str = "Ошибка") -> ChatApi:
        """Make one BFF path fail with a safe `detail`, instead of its script."""
        self.errors[path] = (status, {"detail": detail})
        return self

    def route_snapshots(self, *snapshots: dict) -> ChatApi:
        """Serve the analysis snapshots in order; the last one repeats."""
        self.snapshots = list(snapshots)
        return self

    def route_trace(self, pages: dict[Any, dict]) -> ChatApi:
        """Serve trace pages keyed by the `cursor` query value, `None` for the first."""
        self.trace_pages = dict(pages)
        return self

    def route_rows(self, kind: str, pages: dict[Any, dict]) -> ChatApi:
        """Serve report-row pages of one kind, keyed by the `cursor` query value."""
        self.row_pages = {**self.row_pages, **{(kind, cursor): page for cursor, page in pages.items()}}
        return self

    def route_cancel(self, snapshot: dict) -> ChatApi:
        """Answer the cancel call with the terminal snapshot the run ends in."""
        self.cancel_snapshot = snapshot
        return self

    # -- chat --------------------------------------------------------------

    def _route_chat(self, route: Route) -> None:
        request = route.request
        path = self._api_path(request.url)
        self.requests.append(f"{request.method} {path}")
        if self._fail(route, path):
            return
        if path == "/api/seo/chats" and request.method == "GET":
            route.fulfill(json={"items": [] if self.deleted else [self.chat]})
        elif path == "/api/seo/chats" and request.method == "POST":
            self._reset()
            route.fulfill(status=201, json={"chat": self.chat})
        elif path == f"/api/seo/chats/{self.chat_id}/messages" and request.method == "POST":
            self._turn(route)
        elif path == f"/api/seo/chats/{self.chat_id}/proposal" and request.method == "PUT":
            payload = self._body(route) or {}
            ids = payload.get("connection_ids") if isinstance(payload, dict) else []
            route.fulfill(json={"chat": self.chat, "message": self._proposal(ids if isinstance(ids, list) else [])})
        elif path == f"/api/seo/chats/{self.chat_id}" and request.method == "GET":
            route.fulfill(json={"chat": self.chat, "messages": [], "next_cursor": None})
        elif path == f"/api/seo/chats/{self.chat_id}" and request.method == "DELETE":
            self.deleted = True
            route.fulfill(status=204, body="")
        else:
            route.fulfill(status=404, json={"detail": "Не найдено"})

    def _turn(self, route: Route) -> None:
        """Take the server's own decision for one user message.

        The order is the rule of `ChatService._decide`: a confirmation without a
        proposal is refused, an incomplete draft asks, a confirmation of the
        pending proposal starts the one run, and anything else shows the proposal.
        """
        body = self._body(route) or {}
        text = str(body.get("text", "")) if isinstance(body, dict) else ""
        if self.seq == 0 and text:
            # The real backend titles the chat from its first message.
            self.chat["title"] = text[:80]
        answer = self.answers.pop(0) if self.answers else PROPOSAL_ANSWER
        parsed = self._parse(answer)
        self._merge(parsed.get("params"))
        missing = self._missing()
        self.chat["running"] = False

        messages = [self._message("user", "text", text, None)]
        intent = parsed.get("intent")
        if intent == "confirm" and not self.pending and missing:
            messages.append(self._message("assistant", "text", NOTHING_TO_RUN, None))
        elif missing:
            messages.append(self._message("assistant", "text", QUESTIONS[missing[0]], None))
        elif intent == "confirm" and self.pending:
            self.pending = False
            self.chat["running"] = True
            messages.append(self._message("assistant", "run", None, {"analysis_id": self.analysis_id}))
        else:
            reply = str(parsed.get("reply") or "").strip()
            hint = f"{reply} {PROPOSAL_HINT}" if reply else PROPOSAL_HINT
            messages.append(self._message("assistant", "text", hint, None))
            messages.append(self._proposal([]))
            self.pending = True
        route.fulfill(json={"chat": self.chat, "messages": messages})

    def _reset(self) -> None:
        self.draft = {"url": "", "sphere": "", "seeds": [], "services": []}
        self.pending = False
        self.seq = 0
        self.deleted = False
        self.chat = self._summary("Новый чат")

    def _summary(self, title: str) -> dict[str, Any]:
        return {"id": self.chat_id, "title": title, "updated_at": STAMP, "running": False}

    def _merge(self, params: object) -> None:
        """Fold the four collected fields into the draft, ignoring the rest."""
        if not isinstance(params, dict):
            return
        for field in ("url", "sphere"):
            value = params.get(field)
            if isinstance(value, str) and value.strip():
                self.draft[field] = value.strip()
        for field in ("seeds", "services"):
            value = params.get(field)
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                items = [item for item in value if item.strip()]
                if items:
                    self.draft[field] = items

    def _missing(self) -> list[str]:
        """The fields the assistant still has to ask for, in the backend's order."""
        missing = []
        url = self.draft["url"]
        if not (url.startswith("http://") or url.startswith("https://")):
            missing.append("url")
        if not self.draft["sphere"]:
            missing.append("sphere")
        seeds = self.draft["seeds"]
        if len(seeds) != 3 or len({seed.casefold() for seed in seeds}) != 3:
            missing.append("seeds")
        if not self.draft["services"]:
            missing.append("services")
        return missing

    def _proposal(self, connection_ids: list) -> dict:
        return self._message(
            "assistant",
            "proposal",
            None,
            {
                "status": "pending",
                "url": self.draft["url"],
                "sphere": self.draft["sphere"],
                "seeds": list(self.draft["seeds"]),
                "services": list(self.draft["services"]),
                "connection_ids": list(connection_ids),
                "search_upper": 5,
                "model_upper": 5,
                "generated_limit": 2,
            },
        )

    def _message(self, role: str, kind: str, text: str | None, payload: object) -> dict:
        self.seq += 1
        return {
            "id": f"m{self.seq}",
            "seq": self.seq,
            "role": role,
            "kind": kind,
            "text": text,
            "payload": payload,
            "created_at": STAMP,
        }

    # -- analyses ----------------------------------------------------------

    def _route_analysis(self, route: Route) -> None:
        request = route.request
        path = self._api_path(request.url)
        self.requests.append(f"{request.method} {path}")
        if self._fail(route, path):
            return
        if path == "/api/seo/analyses" and request.method == "GET":
            route.fulfill(json={"items": [], "next_cursor": None})
        elif path == f"/api/seo/analyses/{self.analysis_id}/trace":
            cursor = self._query(request.url, "cursor")
            self.trace_cursors.append(cursor)
            route.fulfill(json=self.trace_pages.get(cursor, {"items": [], "next_cursor": None}))
        elif path == f"/api/seo/analyses/{self.analysis_id}/rows":
            kind = self._query(request.url, "kind")
            cursor = self._query(request.url, "cursor")
            self.row_cursors.append((kind, cursor))
            route.fulfill(json=self.row_pages.get((kind, cursor), {"items": [], "next_cursor": None}))
        elif path == f"/api/seo/analyses/{self.analysis_id}/cancel" and request.method == "POST":
            self.cancel_body = request.post_data
            route.fulfill(json=self.cancel_snapshot if self.cancel_snapshot is not None else self._snapshot())
        elif path == f"/api/seo/analyses/{self.analysis_id}" and request.method == "GET":
            route.fulfill(json=self._snapshot())
        else:
            route.fulfill(status=404, json={"detail": "Не найдено"})

    def _snapshot(self) -> dict:
        """The next scripted snapshot; without a script, a finished run."""
        if not self.snapshots:
            return completed_snapshot(self.analysis_id)
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[-1]

    # -- small helpers -----------------------------------------------------

    def _fail(self, route: Route, path: str) -> bool:
        override = self.errors.get(path)
        if override is None:
            return False
        status, body = override
        route.fulfill(status=status, json=body)
        return True

    def _parse(self, answer: str) -> dict:
        try:
            parsed = json.loads(answer)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _body(route: Route) -> object:
        try:
            return route.request.post_data_json
        except Exception:  # noqa: BLE001 - a missing or non-JSON body is just empty
            return None

    @staticmethod
    def _api_path(url: str) -> str:
        path = url.split("?", 1)[0]
        index = path.find("/api/")
        return path[index:] if index >= 0 else path

    @staticmethod
    def _query(url: str, name: str) -> str | None:
        values = parse_qs(urlsplit(url).query).get(name)
        return values[0] if values else None
