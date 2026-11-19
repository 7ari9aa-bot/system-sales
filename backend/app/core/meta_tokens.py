"""Small shared helpers for Meta access-token lifecycle metadata."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def token_expiry(expires_in: object, *, now: datetime | None = None) -> str | None:
    """Convert Graph's expires_in seconds to an ISO timestamp."""
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return ((now or datetime.now(UTC)) + timedelta(seconds=seconds)).isoformat()
