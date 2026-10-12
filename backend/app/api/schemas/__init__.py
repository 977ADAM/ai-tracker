"""HTTP schemas: the request and response shapes of every endpoint.

They belong to the transport layer on purpose. The domain and the services keep
returning plain values, so a schema change can never reach business rules, and
pydantic stays a dependency of `api` alone.
"""

from .common import ErrorResponse
from .providers import DeletedResponse, ProviderResponse, ProviderWriteRequest

__all__ = [
    "DeletedResponse",
    "ErrorResponse",
    "ProviderResponse",
    "ProviderWriteRequest",
]
