"""Domain rules: models, limits, validation, matching, and report building.

Nothing in this package performs I/O or imports a web framework.
"""

from .limits import LIMITS, SCOPE_OPTIONS
from .models import (
    RESULT_ABSENT,
    RESULT_ERROR,
    RESULT_MENTIONED,
    CheckInput,
    CheckReport,
    CheckSummary,
    Connection,
    PromptResult,
    ProviderCheck,
)

__all__ = [
    "LIMITS",
    "RESULT_ABSENT",
    "RESULT_ERROR",
    "RESULT_MENTIONED",
    "SCOPE_OPTIONS",
    "CheckInput",
    "CheckReport",
    "CheckSummary",
    "Connection",
    "PromptResult",
    "ProviderCheck",
]
