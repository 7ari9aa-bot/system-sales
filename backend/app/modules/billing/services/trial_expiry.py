"""Lock a tenant whose free trial ran out unpaid (and only that tenant).

A new tenant is created ``active`` and its trial lives on the subscription row, so this sweep is
what turns "the trial ended" into "the business API is closed until you pay" (``trial_expired``:
sign-in and billing stay open, see ``identity.services.lifecycle``).

Why it is built the way it is:

* OFF by default. ``settings.trial_lock_starts_at`` empty (or unparseable) means nothing is ever
  locked, so deploying this changes no tenant.
* Only trials that STARTED at or after that timestamp are eligible. Trials that began earlier are
  never touched, by design rather than by a list of exceptions.
* A tenant that has any subscription row other than ``trialing`` is skipped: any trace of having
  paid (active, past_due, canceled, expired) means this path must not lock it.
* ``subscriptions`` is FORCE RLS, so each tenant is read and moved in its own tenant-bound
  transaction with the tenant row locked, and the decision is re-checked under that lock. A
  payment landing between "list the candidates" and "lock them" therefore wins.
* One tenant failing must not starve the batch.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app.core import db as core_db
from app.core.config import get_settings
from app.core.db import bind_tenant

logger = logging.getLogger(__name__)

_REASON = "free trial ended without payment"


def parse_lock_start(raw: str | None) -> datetime | None:
    """The configured start as an aware UTC datetime, or None when the lock is off/invalid."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("trial_expiry.invalid_trial_lock_starts_at value=%r (lock stays OFF)", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _should_lock(session, tenant_id: uuid.UUID, lock_start: datetime, now: datetime) -> bool:
    """True only for a tenant whose every subscription is an expired, post-cutoff trial."""
    rows = (
        await session.execute(
            sa.text(
                "SELECT status, current_period_start, current_period_end "
                "FROM subscriptions WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
    ).all()
    if not rows:
        return False  # never had a trial: nothing to expire
    for status, start, end in rows:
        if status != "trialing":
            return False  # any trace of a paid/ended plan: not this path's business
        if start is None or end is None or start < lock_start or end >= now:
            return False
    return True


async def lock_expired_trials(*, batch_size: int = 100, now: datetime | None = None) -> int:
    """Move every eligible expired trial to ``trial_expired``. Returns how many were locked."""
    from app.modules.identity.services.lifecycle import TenantLifecycleService

    lock_start = parse_lock_start(get_settings().trial_lock_starts_at)
    if lock_start is None:
        return 0
    now = now or datetime.now(UTC)

    # Resolved through the module at call time (not imported by name) so a test can rebind it.
    session_factory = core_db.get_sessionmaker()
    async with session_factory() as session:
        candidate_ids = (
            (
                await session.execute(
                    sa.text(
                        "SELECT id FROM tenants WHERE lifecycle_state = 'active' "
                        "ORDER BY created_at LIMIT :n"
                    ),
                    {"n": max(1, min(batch_size, 500))},
                )
            )
            .scalars()
            .all()
        )

    locked = 0
    for tenant_id in candidate_ids:
        try:
            async with session_factory() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    # Lock the tenant row first so a concurrent payment (which also moves it) waits,
                    # then decide on what is committed.
                    state = (
                        await session.execute(
                            sa.text("SELECT lifecycle_state FROM tenants WHERE id = :t FOR UPDATE"),
                            {"t": tenant_id},
                        )
                    ).scalar_one_or_none()
                    if state != "active":
                        continue
                    if not await _should_lock(session, tenant_id, lock_start, now):
                        continue
                    await TenantLifecycleService.transition(
                        session, tenant_id, "trial_expired", reason=_REASON
                    )
                    locked += 1
        except Exception:  # noqa: BLE001 - one tenant must not starve the batch
            logger.exception("trial_expiry.lock_failed tenant=%s", tenant_id)
    return locked
