"""Domain rules: models, limits, validation, matching, and report building.

Nothing in this package performs I/O or imports a web framework.
"""

from .limits import LIMITS
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
    "CheckInput",
    "CheckReport",
    "CheckSummary",
    "Connection",
    "PromptResult",
    "ProviderCheck",
]
