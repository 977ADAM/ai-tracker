"""Domain rules: models, limits, validation, and matching.

Nothing in this package performs I/O or imports a web framework.
"""

from .models import Connection

__all__ = ["Connection"]
