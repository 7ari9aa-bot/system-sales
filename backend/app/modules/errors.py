"""Shared domain exceptions for module services.

app/core/errors.py may be introduced by a parallel stage; when it exists its
exceptions are re-exported here so the whole codebase raises one canonical
set. Otherwise the fallback classes below are used.
"""

from __future__ import annotations

__all__ = ["ConflictError", "NotFoundError"]

try:  # pragma: no cover - depends on whether the core stage has landed
    from app.core.errors import ConflictError, NotFoundError

except ImportError:  # app/core/errors.py not present (yet) — local fallbacks

    class NotFoundError(LookupError):
        """Requested entity does not exist or belongs to another tenant."""

    class ConflictError(RuntimeError):
        """Operation conflicts with entity state or a uniqueness constraint."""
