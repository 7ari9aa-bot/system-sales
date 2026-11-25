"""§69 — API key rotation gate driven by ``security.api_key_rotation_days``.

The setting controls how long a secret (API key, provider credential) may live
before the system flags it as due for rotation.  Zero means "no forced rotation".

This module reads the tenant-level setting via direct SQL (same pattern as
``app.core.settings_read``) and compares it against a ``SecretReference.rotated_at``
timestamp.  It is the consumer that makes ``security.api_key_rotation_days``
*enforced* — without it the setting is a switch wired to nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def is_rotation_due(
    rotated_at: datetime | None,
    rotation_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """True when the secret has lived past its rotation window.

    * ``rotation_days <= 0``: rotation is disabled → always False.
    * ``rotated_at is None``: never rotated → always True (overdue from day one).
    * Otherwise: True when ``now - rotated_at`` exceeds ``rotation_days``.
    """
    if rotation_days <= 0:
        return False
    if rotated_at is None:
        return True
    now = now or datetime.now(UTC)
    # Make both sides aware so subtraction is valid across naive/aware mixes.
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=UTC)
    return (now - rotated_at) > timedelta(days=rotation_days)


async def resolve_rotation_days(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Read ``security.api_key_rotation_days`` at tenant scope via direct SQL.

    Returns the registry default (90) when no override exists.
    """
    row = (
        await session.execute(
            text(
                "SELECT value->'v' FROM tenant_settings "
                "WHERE tenant_id = :t AND key = 'security.api_key_rotation_days' "
                "AND scope = 'tenant'"
            ),
            {"t": tenant_id},
        )
    ).scalar_one_or_none()
    if isinstance(row, (int, float)) and not isinstance(row, bool):
        return int(row)
    return 90


async def check_secret_rotation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    rotated_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """High-level gate: resolve the setting, then check the secret's age.

    This is the function callers use — it ties the setting to the behaviour.
    """
    days = await resolve_rotation_days(session, tenant_id)
    return is_rotation_due(rotated_at, days, now=now)


async def due_secret_references(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return every active ``SecretReference`` whose age exceeds the rotation window.

    Used by a scheduled sweep to surface keys that need attention.
    """
    days = await resolve_rotation_days(session, tenant_id)
    if days <= 0:
        return []
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            text(
                "SELECT id, provider, vault_key, rotated_at, version "
                "FROM secret_references "
                "WHERE tenant_id = :t AND status = 'active'"
            ),
            {"t": tenant_id},
        )
    ).all()
    due: list[dict[str, Any]] = []
    for ref_id, provider, vault_key, rotated_at, version in rows:
        if is_rotation_due(rotated_at, days, now=now):
            due.append(
                {
                    "id": ref_id,
                    "provider": provider,
                    "vault_key": vault_key,
                    "rotated_at": rotated_at,
                    "version": version,
                }
            )
    return due
