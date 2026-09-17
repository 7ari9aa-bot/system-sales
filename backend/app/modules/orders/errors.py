"""ORDERS domain exceptions — stock-aware errors shared with inventory."""

from __future__ import annotations

__all__ = ["InsufficientStockError"]

try:  # pragma: no cover - depends on whether the core stage has landed
    from app.core.errors import InsufficientStockError

except ImportError:  # app/core/errors.py not present (yet) — local fallback

    class InsufficientStockError(RuntimeError):
        """A stock operation would drive a balance (or availability) below zero."""
