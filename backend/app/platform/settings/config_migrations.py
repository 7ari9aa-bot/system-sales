"""Config migration framework — versioned, per-tenant settings migrations.

Each migration has a unique ``id`` (ordered), a human description, and an
``apply`` coroutine that transforms ``tenant_settings`` rows for one tenant.
The runner (``ConfigMigrationService.run_pending``) checks the
``setting_migration_log`` table to skip already-applied migrations, making
the whole process idempotent.

Migrations are the settings equivalent of Alembic schema migrations: they
rename keys, transform values, or clean up obsolete overrides when the
registry evolves. Unlike Alembic, they are per-tenant — each tenant's
settings evolve independently, and the migration log is tenant-scoped.

Adding a migration
------------------
1. Define a ``ConfigMigration`` with a new, higher ``id``.
2. Append it to ``MIGRATIONS``.
3. The next time ``run_pending`` is called (manually or by a worker), it
   applies to every tenant that hasn't seen it yet.

Migrations must be **idempotent within themselves**: if the runner crashes
after the migration's DB changes but before the log row is written, a
re-run should either no-op (because the data is already in the target state)
or tolerate the intermediate state gracefully.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.settings.models import SettingMigrationLog, TenantSetting


@dataclass(frozen=True, slots=True)
class ConfigMigration:
    """One named, ordered settings migration."""

    id: str
    description: str
    apply: Callable[[AsyncSession, uuid.UUID], Awaitable[None]]


# ---------------------------------------------------------------------------
# Migration primitives
# ---------------------------------------------------------------------------


async def _rename_key(
    session: AsyncSession, tenant_id: uuid.UUID, old_key: str, new_key: str
) -> None:
    """Rename all ``tenant_settings`` rows from ``old_key`` to ``new_key``.

    Idempotent: if ``old_key`` has no rows, nothing happens.
    """
    await session.execute(
        update(TenantSetting)
        .where(
            TenantSetting.tenant_id == tenant_id,
            TenantSetting.key == old_key,
        )
        .values(key=new_key)
    )


async def _transform_value(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    transform: Callable[[object], object],
) -> None:
    """Apply ``transform`` to the stored value of every override for ``key``.

    The value column stores ``{"v": <actual>}``; the transform receives and
    returns the unwrapped value. Idempotent if ``transform`` is idempotent.
    """
    rows = (
        (
            await session.execute(
                select(TenantSetting).where(
                    TenantSetting.tenant_id == tenant_id,
                    TenantSetting.key == key,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        current = row.value.get("v") if isinstance(row.value, dict) else row.value
        row.value = {"v": transform(current)}


# ---------------------------------------------------------------------------
# Registered migrations (ordered by id)
# ---------------------------------------------------------------------------

MIGRATIONS: list[ConfigMigration] = [
    # No migrations are registered yet.  This list is intentionally empty:
    # the framework is in place (runner, log table, idempotency) but no
    # setting key has been renamed or had its value format changed since
    # the framework was introduced.  When that happens, add a migration
    # here following the pattern below:
    #
    # ConfigMigration(
    #     id="001_rename_discount_cap",
    #     description="Rename pos.discount_cap → pos.max_discount_pct",
    #     apply=lambda s, t: _rename_key(s, t, "pos.discount_cap", "pos.max_discount_pct"),
    # ),
]


def latest_version() -> str:
    """The highest migration id, or ``"0"`` if none are registered."""
    return MIGRATIONS[-1].id if MIGRATIONS else "0"


async def run_pending(
    session: AsyncSession, tenant_id: uuid.UUID, *, applied_by: uuid.UUID | None = None
) -> list[str]:
    """Apply all migrations this tenant hasn't seen yet.

    Returns the list of migration ids that were applied (empty if up-to-date).
    Idempotent: the ``setting_migration_log`` table prevents re-application.
    """
    if not MIGRATIONS:
        return []

    # Load already-applied migration ids for this tenant.
    applied_ids = set(
        (
            await session.execute(
                select(SettingMigrationLog.migration_id).where(
                    SettingMigrationLog.tenant_id == tenant_id
                )
            )
        ).scalars()
    )

    newly_applied: list[str] = []
    for migration in MIGRATIONS:
        if migration.id in applied_ids:
            continue
        await migration.apply(session, tenant_id)
        session.add(
            SettingMigrationLog(
                tenant_id=tenant_id,
                migration_id=migration.id,
                description=migration.description,
                applied_by=applied_by,
            )
        )
        await session.flush()
        newly_applied.append(migration.id)

    return newly_applied
