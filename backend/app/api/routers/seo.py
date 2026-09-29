"""Create, inspect, list, cancel, and delete durable SEO analyses.

The router only declares routes and dependencies. Validation, storage, and the
agent runtime live in `domain/seo.py`, `db/seo.py`, and `service/seo_agents.py`;
nothing here starts a paid call inside the HTTP request.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import SeoServiceDep
from app.api.schemas import ErrorResponse
from app.api.schemas.seo import (
    SeoAnalysisCreatedResponse,
    SeoAnalysisRequest,
    SeoHistoryPageResponse,
    SeoRowsResponse,
    SeoSnapshotResponse,
    SeoTracePageResponse,
)
from app.domain.seo import GENERATED_QUERY_LIMIT
from app.domain.seo_tools import (
    MAX_SEARCH_REQUESTS,
    MAX_SUPERVISOR_HANDOFFS,
    MAX_TOOL_CALLS,
)
from app.domain.site_fetch import MAX_FETCH_PAGES

router = APIRouter(prefix="/seo/analyses", tags=["seo"])
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
    409: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
}


def _public_snapshot(snapshot: dict) -> dict:
    """Pair the stored budget counters with the caps the run was held to.

    The repository stores what was spent; the caps are the fixed constants of the
    run, so the interface can show "used of limit" without inventing numbers.
    """
    counts = snapshot.get("budget") or {}
    connections = len(snapshot.get("input", {}).get("connection_ids", ()))
    budget = {
        "pages": {"used": int(counts.get("pages", 0)), "limit": MAX_FETCH_PAGES},
        "searches": {"used": int(counts.get("searches", 0)), "limit": MAX_SEARCH_REQUESTS},
        "model_answers": {
            "used": int(counts.get("model_rows", 0)),
            "limit": GENERATED_QUERY_LIMIT * connections,
        },
        "tool_calls": {"used": int(counts.get("tool_calls", 0)), "limit": MAX_TOOL_CALLS},
        "handoffs": {"used": int(counts.get("handoffs", 0)), "limit": MAX_SUPERVISOR_HANDOFFS},
        "seed_searches": int(counts.get("seed_searches", 0)),
        "model_rows": int(counts.get("model_rows", 0)),
        "steps": int(counts.get("steps", 0)),
        "agent_steps": {
            str(agent): int(used) for agent, used in (counts.get("agent_steps") or {}).items()
        },
    }
    return {**snapshot, "budget": budget}


@router.post("", status_code=202, response_model=SeoAnalysisCreatedResponse, responses=ERROR_RESPONSES)
async def create_analysis(seo: SeoServiceDep, payload: SeoAnalysisRequest) -> dict:
    """Create the durable analysis and answer at once; the six stages run in the background."""
    return await seo.start(payload.model_dump())


@router.get("", response_model=SeoHistoryPageResponse, responses=ERROR_RESPONSES)
def list_analyses(seo: SeoServiceDep, cursor: str | None = None) -> dict:
    return seo.list_page(cursor)


@router.get("/{id}", response_model=SeoSnapshotResponse, responses=ERROR_RESPONSES)
def get_analysis(seo: SeoServiceDep, id: str) -> dict:
    return _public_snapshot(seo.snapshot(id))


@router.get("/{id}/rows", response_model=SeoRowsResponse, responses=ERROR_RESPONSES)
def get_analysis_rows(
    seo: SeoServiceDep, id: str, kind: str, cursor: str | None = None,
) -> dict:
    """Serve the paginated detail; model answers are returned only here."""
    return seo.rows_page(id, kind, cursor)


@router.get("/{id}/trace", response_model=SeoTracePageResponse, responses=ERROR_RESPONSES)
def get_analysis_trace(seo: SeoServiceDep, id: str, cursor: str | None = None) -> dict:
    """Serve the paginated agent trace: safe arguments and short results only."""
    return seo.trace_page(id, cursor)


@router.post("/{id}/cancel", response_model=SeoSnapshotResponse, responses=ERROR_RESPONSES)
async def cancel_analysis(seo: SeoServiceDep, id: str) -> dict:
    """Stop new submissions and polls of one active analysis; the finished rows stay."""
    return _public_snapshot(seo.cancel(id))


@router.delete("/{id}", status_code=204, responses=ERROR_RESPONSES)
def delete_analysis(seo: SeoServiceDep, id: str) -> Response:
    """Delete a terminal analysis; an active one is a conflict."""
    seo.delete(id)
    return Response(status_code=204)
