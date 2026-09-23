"""Pure domain models. They are plain dataclasses with no I/O and no framework types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RESULT_MENTIONED = "mentioned"
RESULT_ABSENT = "absent"
RESULT_ERROR = "error"

KIND_OPENAI = "openai"
KIND_GIGACHAT = "gigachat"
SUPPORTED_KINDS = (KIND_OPENAI, KIND_GIGACHAT)


@dataclass(frozen=True)
class Connection:
    """A saved provider connection. Never holds an API key."""

    id: str
    name: str
    kind: str
    model: str
    endpoint: str | None = None
    scope: str | None = None
    thinking_disabled: bool = False
    preset: bool = False

    def metadata(self) -> dict[str, Any]:
        """The non-secret part that is persisted to disk."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "endpoint": self.endpoint,
            "model": self.model,
            **({"scope": self.scope} if self.scope is not None else {}),
        }


@dataclass(frozen=True)
class CheckInput:
    """A normalized, validated check request."""

    brand: str
    domain: str
    prompts: tuple[str, ...]


@dataclass(frozen=True)
class PromptResult:
    """The outcome of one prompt against one provider."""

    prompt: str
    answer: str | None
    mentioned: bool | None
    error: str | None
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "answer": self.answer,
            "mentioned": self.mentioned,
            "error": self.error,
            "status": self.status,
        }


@dataclass(frozen=True)
class ProviderCheck:
    """All prompt results for one provider, plus its own counters."""

    provider_id: str
    provider_name: str
    results: tuple[PromptResult, ...]

    @property
    def successful(self) -> int:
        return sum(1 for result in self.results if result.status != RESULT_ERROR)

    @property
    def failed(self) -> int:
        return sum(1 for result in self.results if result.status == RESULT_ERROR)

    @property
    def mentioned(self) -> int:
        return sum(1 for result in self.results if result.mentioned)

    def summary(self) -> dict[str, int]:
        return {"successful": self.successful, "failed": self.failed, "mentioned": self.mentioned}

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "summary": self.summary(),
            "results": [result.as_dict() for result in self.results],
        }


@dataclass(frozen=True)
class CheckSummary:
    """The run-wide counters and the Russian labels the report shows."""

    successful: int
    failed: int
    mentioned: int
    mention_percent: int | None
    visibility_label: str
    mentions_label: str
    errors_label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "successful": self.successful,
            "failed": self.failed,
            "mentioned": self.mentioned,
            "mention_percent": self.mention_percent,
            "visibility_label": self.visibility_label,
            "mentions_label": self.mentions_label,
            "errors_label": self.errors_label,
        }


@dataclass(frozen=True)
class CheckReport:
    """The complete response body of a finished check."""

    brand: str
    domain: str
    checks: tuple[ProviderCheck, ...]
    summary: CheckSummary

    def rows(self) -> list[dict[str, Any]]:
        return [
            dict(result.as_dict(), provider_name=check.provider_name)
            for check in self.checks
            for result in check.results
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "domain": self.domain,
            "checks": [check.as_dict() for check in self.checks],
            "summary": self.summary.as_dict(),
            "rows": self.rows(),
        }
