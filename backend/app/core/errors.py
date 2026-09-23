"""Errors whose messages are safe to show to the app user.

The API layer maps these types to HTTP statuses; every other layer raises them
instead of inventing ad-hoc exceptions. Messages never contain keys, response
bodies, or local paths.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-readable application errors."""


class ValidationError(AppError):
    """Request input is missing, malformed, or outside the allowed limits."""


class ConfigurationError(AppError):
    """A connection could not be configured, stored, or prepared for a call."""


class StorageError(AppError):
    """Local metadata storage could not be read or written."""


class ProviderError(AppError):
    """A model provider call failed in a way that is safe to report."""
