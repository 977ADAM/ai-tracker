"""Run-wide counters and the Russian labels the report shows."""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.models import CheckSummary, ProviderCheck


def _russian_error_word(count: int) -> str:
    last_two, last = count % 100, count % 10
    if 11 <= last_two <= 14:
        return "ошибок"
    if last == 1:
        return "ошибка"
    if 2 <= last <= 4:
        return "ошибки"
    return "ошибок"


def _rounded_percent(mentioned: int, successful: int) -> int:
    return (mentioned * 100 + successful // 2) // successful


def summarize(checks: Iterable[ProviderCheck]) -> CheckSummary:
    """Sum every provider's counters and build the labels shown above the report."""
    collected = tuple(checks)
    successful = sum(check.successful for check in collected)
    failed = sum(check.failed for check in collected)
    mentioned = sum(check.mentioned for check in collected)

    mention_percent = _rounded_percent(mentioned, successful) if successful else None
    return CheckSummary(
        successful=successful,
        failed=failed,
        mentioned=mentioned,
        mention_percent=mention_percent,
        visibility_label=f"{mention_percent}%" if mention_percent is not None else "—",
        mentions_label=(
            f"{mentioned} из {successful} успешных ответов" if successful else "Нет успешных ответов"
        ),
        errors_label=f"{failed} {_russian_error_word(failed)} API",
    )
