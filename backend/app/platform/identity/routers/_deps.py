"""Shared router helpers and dependencies for the identity module."""

from __future__ import annotations

from fastapi import Request

_CLIENT_TTL = 60 * 60 * 24 * 30  # refresh cookie life if cookie mode used


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


async def bind_tenant_user(session, user_id) -> None:
    """Bind the `app.user_id` GUC (transaction-scoped, pooler-safe)."""
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config(:guc, :user_id, true)"),
        {"guc": "app.user_id", "user_id": str(user_id)},
    )
