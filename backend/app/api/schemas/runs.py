"""Public schemas for saved combined runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RunRequest(BaseModel):
    project_id: str = ""
    brand: str = ""
    domain: str = ""
    prompts: list[str] | None = None
    prompts_text: str | None = None
    provider_ids: list[str] = []
    regions: list[int] = []
    region_targets: list[dict[str, object]] | None = None


class RunCreatedResponse(BaseModel):
    id: str
    status: Literal["pending", "done", "interrupted"]


class ModelRunRow(BaseModel):
    provider_id: str
    prompt_index: int
    provider_name: str
    prompt: str
    status: str
    answer: str | None
    mentioned: bool | None
    error: str | None


class SearchRunRow(BaseModel):
    search_index: int
    prompt_index: int
    region_index: int
    prompt: str
    region_id: int
    region_name: str
    engine: str = "yandex"
    status: str
    position: int | None
    url: str | None
    error: str | None


class SummaryRunRow(BaseModel):
    prompt: str
    source: str
    language: str
    region: str
    ai_answer: str
    site_found: str
    position: str
    brand_found: str
    status: str


class RunSnapshotResponse(BaseModel):
    id: str
    project_id: str
    created_at: str
    finished_at: str | None
    status: Literal["pending", "done", "interrupted"]
    brand: str
    domain: str
    prompts: list[str]
    provider_ids: list[str]
    regions: list[int]
    models: list[ModelRunRow]
    search: list[SearchRunRow]
    summary_rows: list[SummaryRunRow]


class RunHistoryItem(BaseModel):
    id: str
    created_at: str
    status: Literal["pending", "done", "interrupted"]
    prompts: list[str]


class RunHistoryPage(BaseModel):
    items: list[RunHistoryItem]
    next_cursor: str | None
