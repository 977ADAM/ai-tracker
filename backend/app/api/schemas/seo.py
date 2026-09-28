"""Strict public schemas for durable SEO analyses.

Every response is a projection of what `SeoRepository`/`SeoService` already
return. The snapshot deliberately carries no model answer text and no Yandex
operation ID; the per-row answers are served by the paginated `rows` resource
instead, so a single response never grows into megabytes and a secret or an
internal identifier never leaves the database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr

SeoAnalysisStatus = Literal["running", "completed", "failed", "interrupted", "cancelled"]
SeoStageStatus = Literal["pending", "running", "done", "error", "skipped"]


class SeoAnalysisRequest(BaseModel):
    """The five form fields of a one-shot SEO analysis."""

    model_config = ConfigDict(extra="forbid")

    url: StrictStr
    sphere: StrictStr
    seeds: list[StrictStr]
    services: list[StrictStr]
    connection_ids: list[StrictStr]


class SeoEstimateResponse(BaseModel):
    search_upper: int
    model_upper: int
    generated_limit: int
    connections: int


class SeoAnalysisCreatedResponse(BaseModel):
    id: str
    status: Literal["running"]
    estimate: SeoEstimateResponse


class SeoMetricResponse(BaseModel):
    denominator: int
    successes: int
    share: float | None
    average_position: float | None


class SeoSearchMetricsResponse(BaseModel):
    overall: SeoMetricResponse
    branded: SeoMetricResponse
    unbranded: SeoMetricResponse


class SeoSiteAiMetricsResponse(BaseModel):
    name: SeoMetricResponse
    host: SeoMetricResponse
    combined: SeoMetricResponse


class SeoSiteAiBlockResponse(SeoSiteAiMetricsResponse):
    branded: SeoSiteAiMetricsResponse
    unbranded: SeoSiteAiMetricsResponse


class SeoCountsResponse(BaseModel):
    queries: int
    search_rows: int
    model_rows: int
    search_errors: int
    model_errors: int


class SeoSiteAggregatesResponse(BaseModel):
    search: SeoSearchMetricsResponse
    ai: dict[str, SeoSiteAiBlockResponse]


class SeoCompetitorAggregatesResponse(BaseModel):
    host: str
    title: str
    occurrences: int
    average_position: float
    seed_indexes: list[int]
    search: SeoSearchMetricsResponse
    ai: dict[str, dict[str, SeoMetricResponse]]


class SeoCategoryAggregatesResponse(BaseModel):
    search: SeoMetricResponse
    ai: dict[str, SeoMetricResponse]


class SeoAggregatesResponse(BaseModel):
    site: SeoSiteAggregatesResponse
    competitors: list[SeoCompetitorAggregatesResponse]
    categories: dict[str, SeoCategoryAggregatesResponse]
    services: dict[str, SeoCategoryAggregatesResponse]
    counts: SeoCountsResponse


class SeoStageResponse(BaseModel):
    stage: int
    status: SeoStageStatus
    error: str | None
    counters: dict[str, int]
    updated_at: str


class SeoAnalysisInputResponse(BaseModel):
    url: str
    host: str
    sphere: str
    seeds: list[str]
    services: list[str]
    connection_ids: list[str]


class SeoPageResponse(BaseModel):
    url: str
    title: str


class SeoCandidateResponse(BaseModel):
    host: str
    title: str
    occurrences: int
    average_position: float
    seed_indexes: list[int]
    recurring: bool


class SeoQueryFlagsResponse(BaseModel):
    mentions_company_name: bool
    mentions_company_host: bool
    mentions_candidate_host: bool
    branded: bool


class SeoQueryResponse(BaseModel):
    index: int
    text: str
    category: str
    service: str | None
    flags: SeoQueryFlagsResponse


class SeoReadinessResponse(BaseModel):
    report_ready: bool
    summary_ready: bool
    queries_ready: bool
    has_submitted_search_rows: bool
    has_unsubmitted_search_rows: bool
    has_unfinished_model_rows: bool
    search_rows: int
    model_rows: int


class SeoSnapshotResponse(BaseModel):
    """The saved analysis without model answers and without operation IDs."""

    id: str
    status: SeoAnalysisStatus
    created_at: str
    updated_at: str
    finished_at: str | None
    input: SeoAnalysisInputResponse
    estimate: SeoEstimateResponse
    company_name: str
    services: list[str]
    pages: list[SeoPageResponse]
    stages: list[SeoStageResponse]
    candidates: list[SeoCandidateResponse]
    queries: list[SeoQueryResponse]
    summary: str | None
    counters: SeoCountsResponse
    readiness: SeoReadinessResponse
    aggregates: SeoAggregatesResponse


class SeoHistoryItemResponse(BaseModel):
    id: str
    created_at: str
    finished_at: str | None
    status: SeoAnalysisStatus
    sphere: str
    host: str
    company_name: str
    counters: SeoCountsResponse


class SeoHistoryPageResponse(BaseModel):
    items: list[SeoHistoryItemResponse]
    next_cursor: str | None


class SeoSearchRowResponse(BaseModel):
    """One saved Yandex row; pending statuses are possible while the run is active."""

    query_index: int
    query: str | None
    category: str | None
    service: str | None
    status: str
    site_position: int | None
    site_url: str | None
    error: str | None


class SeoModelRowResponse(BaseModel):
    """One saved model answer, served only by the paginated detail resource."""

    query_index: int
    connection_id: str
    provider_name: str
    status: str
    answer: str | None
    name_mentioned: bool | None
    host_mentioned: bool | None
    error: str | None
    query: str | None
    category: str | None
    service: str | None


class SeoRowsResponse(BaseModel):
    items: list[SeoModelRowResponse | SeoSearchRowResponse]
    next_cursor: str | None
