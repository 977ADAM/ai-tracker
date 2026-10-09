"""Allowlisted project payloads; domain validation owns business limits."""

from pydantic import BaseModel, ConfigDict


class ProjectQuerySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    category: str | None = None
    group: str | None = None


class CompetitorSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str
    site_url: str = ""


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    brand: str
    site_url: str
    include_subdomains: bool = True
    brand_description: str = ""
    brand_aliases: list[str] = []
    competitors: list[CompetitorSchema] = []
    queries: list[ProjectQuerySchema] = []
    connection_ids: list[str] = []
    yandex_enabled: bool = False
    yandex_region: int = 213


class ProjectResponse(ProjectRequest):
    model_config = ConfigDict(extra="ignore")
    id: str
    revision: int
    created_at: str
    updated_at: str
