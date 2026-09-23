"""Runtime configuration, shared errors, and the composition root."""

from .config import ConnectionPreset, Settings
from .errors import (
    AppError,
    ConfigurationError,
    ProviderError,
    StorageError,
    ValidationError,
)

__all__ = [
    "AppError",
    "ConfigurationError",
    "ConnectionPreset",
    "ProviderError",
    "Settings",
    "StorageError",
    "ValidationError",
]
