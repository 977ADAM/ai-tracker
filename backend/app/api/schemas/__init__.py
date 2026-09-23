"""HTTP schemas: the request and response shapes of every endpoint.

They belong to the transport layer on purpose. The domain and the services keep
returning plain values, so a schema change can never reach business rules, and
pydantic stays a dependency of `api` alone.
"""

from .checks import (
    CheckRequest,
    CheckResponse,
    CheckRowResponse,
    CheckSummaryResponse,
    PromptResultResponse,
    ProviderCheckResponse,
    ProviderCheckSummary,
)
from .common import ErrorResponse
from .form import FormLimits, FormResponse, ScopeOption
from .providers import DeletedResponse, ProviderResponse, ProviderWriteRequest

__all__ = [
    "CheckRequest",
    "CheckResponse",
    "CheckRowResponse",
    "CheckSummaryResponse",
    "DeletedResponse",
    "ErrorResponse",
    "FormLimits",
    "FormResponse",
    "PromptResultResponse",
    "ProviderCheckResponse",
    "ProviderCheckSummary",
    "ProviderResponse",
    "ProviderWriteRequest",
    "ScopeOption",
]
