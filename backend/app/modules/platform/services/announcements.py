"""Platform announcements — the resolved read path merchants see.

The owner console writes the rows; this service answers the only two questions
the merchant dashboard has: "is there a live notice for THIS tenant and THIS
user?" and "remember that THIS user dismissed it". Filtering happens in
Python, not in a JSONB operator, so an empty ``audience.tenant_ids`` list can
never silently widen into "every tenant" — an empty target list targets
nobody, on purpose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import PlatformAnnouncement, PlatformAnnouncementDismissal

# A live announcement window is small by construction (the console composes
# notices days ahead at most), but the read path still refuses to load the
# whole table: this bound covers any realistic schedule without paging.
_MAX_CANDIDATES = 50


async def active_for_user(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> PlatformAnnouncement | None:
    """The newest live announcement visible to this tenant and not dismissed.

    Live means: ``is_active``, ``now()`` inside ``[starts_at, ends_at)``,
    audience covers the tenant, and no dismissal row for this user.
    """
    now = datetime.now(UTC)
    candidates = (
        (
            await session.execute(
                select(PlatformAnnouncement)
                .where(
                    PlatformAnnouncement.is_active.is_(True),
                    PlatformAnnouncement.starts_at <= now,
                )
                .order_by(PlatformAnnouncement.created_at.desc())
                .limit(_MAX_CANDIDATES)
            )
        )
        .scalars()
        .all()
    )

    visible = [
        row
        for row in candidates
        if (row.ends_at is None or row.ends_at > now) and _covers_tenant(row.audience, tenant_id)
    ]
    if not visible:
        return None

    dismissed_ids = set(
        (
            await session.execute(
                select(PlatformAnnouncementDismissal.announcement_id).where(
                    PlatformAnnouncementDismissal.user_id == user_id,
                    PlatformAnnouncementDismissal.announcement_id.in_([row.id for row in visible]),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in visible:
        if row.id not in dismissed_ids:
            return row
    return None


def _covers_tenant(audience: dict | None, tenant_id: uuid.UUID) -> bool:
    """NULL audience = everyone; an explicit list must CONTAIN the tenant."""
    if audience is None:
        return True
    tenant_ids = audience.get("tenant_ids")
    if not isinstance(tenant_ids, list):
        # A malformed audience block must not widen into "everyone".
        return False
    return str(tenant_id) in {str(value) for value in tenant_ids}


async def dismiss(session: AsyncSession, announcement_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Record a dismissal; idempotent via the composite PK. True on first write.

    An unknown announcement id is a no-op (False), never an orphan tombstone
    row that would violate the FK.
    """
    exists = (
        await session.execute(
            select(PlatformAnnouncement.id).where(PlatformAnnouncement.id == announcement_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        return False
    result = await session.execute(
        pg_insert(PlatformAnnouncementDismissal)
        .values(announcement_id=announcement_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["announcement_id", "user_id"])
    )
    return (result.rowcount or 0) > 0
