"""Spec §166 — Notification infrastructure enhancements.

Extends the existing Notification model with:
    NotificationDigest      — aggregated notifications (dedupe)
    NotificationAggregator  — prevents notification storms (40 updates → 1)

§166: "40 updates for the same conversation should not produce 40
notifications. Dedupe/aggregation."

``NotificationPreference`` is NOT declared here: the canonical model lives in
``app.modules.platform.models`` (re-exported by ``app.modules.notifications.models``).
This module previously re-declared ``__tablename__ = "notification_preferences"``,
so importing it next to the canonical model raised SQLAlchemy table-redefinition
(InvalidRequestError) — a latent startup crash, hidden only because nothing
imported the module. It now binds the canonical class instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    select,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin

# The canonical NotificationPreference (app.modules.platform.models), reached
# through this module's own re-export surface rather than a second direct
# platform import — the module-boundary ratchet (tests/test_module_boundaries.py)
# is at its baseline, and same-module imports do not count against it.
from app.modules.notifications.models import NotificationPreference


class NotificationDigest(TenantMixin, TimestampMixin, Base):
    """Aggregated notification group (§166 dedupe).

    When multiple notifications share the same dedupe_key (e.g. 40
    conversation updates), they are aggregated into a single digest.
    The digest is delivered as one notification.
    """

    __tablename__ = "notification_digests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    # The dedupe key — e.g. "conversation:8821"
    dedupe_key: Mapped[str] = mapped_column(String(255))
    # Aggregated count
    count: Mapped[int] = mapped_column(Integer, server_default="1")
    # The latest notification payload
    latest_payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # First and last occurrence — TIMESTAMPTZ in the migration (§166), so the
    # model must declare timezone=True or asyncpg gets a naive datetime.
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # allowed: pending | delivered | expired
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    # Delivery channels: {in_app: bool, email: bool, push: bool}
    channels: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index("ix_notif_digests_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_notif_digests_dedupe", "dedupe_key", "status"),
    )


class NotificationAggregator:
    """§166: dedupe and aggregate notifications.

    Rules:
    - Same dedupe_key within the digest window → increment count
    - Critical priority bypasses digest (sent immediately)
    - Quiet hours: hold non-critical, deliver in next window
    """

    @staticmethod
    async def should_send_immediately(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        priority: str = "information",
    ) -> bool:
        """Check if a notification should be sent immediately or digested.

        Falls back to the tenant-level ``notifications.quiet_hours_*`` and
        ``notifications.digest_mode`` settings when no user preference exists.
        """
        # Critical always sends immediately
        if priority == "critical":
            return True

        # Check user-level quiet hours first
        pref = await NotificationAggregator._get_preference(session, tenant_id, user_id)
        if pref and NotificationAggregator._in_quiet_hours(pref):
            return False

        # Tenant-level quiet hours fallback (notifications.quiet_hours_start/end)
        if pref is None or not pref.quiet_start:
            if await NotificationAggregator._tenant_quiet_hours_active(session, tenant_id):
                return False

        # Non-critical with digest enabled → hold
        if pref and pref.digest_enabled:
            return False

        # Tenant-level digest mode fallback (notifications.digest_mode).
        # Read via app.core.settings_read (no import cycle with settings).
        if pref is None:
            from app.core.settings_read import resolve_setting

            mode = await resolve_setting(session, tenant_id, "notifications.digest_mode")
            if mode and mode != "realtime":
                return False

        return True

    @staticmethod
    async def _tenant_quiet_hours_active(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
        """Check tenant-level quiet hours settings as a fallback."""
        from app.core.settings_read import resolve_settings

        settings = await resolve_settings(
            session,
            tenant_id,
            ["notifications.quiet_hours_start", "notifications.quiet_hours_end"],
        )
        start = settings["notifications.quiet_hours_start"]
        end = settings["notifications.quiet_hours_end"]
        if not start or not end:
            return False
        now_time = datetime.now(UTC).time()
        from datetime import time as _time

        h1, m1 = int(start[:2]), int(start[3:5])
        h2, m2 = int(end[:2]), int(end[3:5])
        t_start = _time(h1, m1)
        t_end = _time(h2, m2)
        if t_start <= t_end:
            return t_start <= now_time <= t_end
        return now_time >= t_start or now_time <= t_end

    @staticmethod
    async def add_to_digest(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        dedupe_key: str,
        payload: dict,
        channels: dict,
    ) -> NotificationDigest:
        """Add a notification to a digest (or create one)."""
        existing = (
            await session.execute(
                select(NotificationDigest).where(
                    NotificationDigest.tenant_id == tenant_id,
                    NotificationDigest.user_id == user_id,
                    NotificationDigest.dedupe_key == dedupe_key,
                    NotificationDigest.status == "pending",
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.count += 1
            existing.latest_payload = payload
            existing.last_at = datetime.now(UTC)
            existing.channels = channels
            await session.flush()
            return existing

        digest = NotificationDigest(
            tenant_id=tenant_id,
            user_id=user_id,
            dedupe_key=dedupe_key,
            count=1,
            latest_payload=payload,
            channels=channels,
            status="pending",
        )
        session.add(digest)
        await session.flush()
        return digest

    @staticmethod
    async def _get_preference(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NotificationPreference | None:
        return (
            await session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.tenant_id == tenant_id,
                    NotificationPreference.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    def _in_quiet_hours(pref: NotificationPreference) -> bool:
        """Check if current time is within the user's quiet hours."""
        if not pref.quiet_start or not pref.quiet_end:
            return False
        # Simple check — production would use timezone-aware comparison
        now_time = datetime.now(UTC).time()
        if pref.quiet_start <= pref.quiet_end:
            return pref.quiet_start <= now_time <= pref.quiet_end
        # Overnight window (e.g. 22:00 → 06:00)
        return now_time >= pref.quiet_start or now_time <= pref.quiet_end
