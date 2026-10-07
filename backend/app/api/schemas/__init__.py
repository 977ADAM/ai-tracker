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
from .form import FormLimits, FormResponse
from .providers import DeletedResponse, ProviderResponse, ProviderWriteRequest
from .search import (
    SearchCreatedResponse,
    SearchRegionResponse,
    SearchRequest,
    SearchResultResponse,
    SearchSnapshotResponse,
    SearchSummaryResponse,
)
from .seo_chat import (
    ChatCreatedResponse,
    ChatDetailResponse,
    ChatListResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatMessagesResponse,
    ChatSummaryResponse,
    ProposalResponse,
    ProposalUpdateRequest,
)

__all__ = [
    "ChatCreatedResponse",
    "ChatDetailResponse",
    "ChatListResponse",
    "ChatMessageRequest",
    "ChatMessageResponse",
    "ChatMessagesResponse",
    "ChatSummaryResponse",
    "CheckRequest",
    "CheckResponse",
    "CheckRowResponse",
    "CheckSummaryResponse",
    "DeletedResponse",
    "ErrorResponse",
    "FormLimits",
    "FormResponse",
    "PromptResultResponse",
    "ProposalResponse",
    "ProposalUpdateRequest",
    "ProviderCheckResponse",
    "ProviderCheckSummary",
    "ProviderResponse",
    "ProviderWriteRequest",
    "SearchCreatedResponse",
    "SearchRegionResponse",
    "SearchRequest",
    "SearchResultResponse",
    "SearchSnapshotResponse",
    "SearchSummaryResponse",
]
