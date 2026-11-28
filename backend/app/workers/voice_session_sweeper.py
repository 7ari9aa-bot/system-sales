"""The voice session sweeper, driven across tenants.

``app.modules.voice.application.session_sweeper`` decides and writes; this module
owns the loop around it: enumerate the active tenants, open ONE transaction per
tenant with ``bind_tenant``, let the service flush, and commit. That split is the
module rule in this repo — a service never commits, and ``voice_sessions`` is
FORCE RLS, so an unbound transaction reads zero rows and would look like a sweep
that found nothing to do.

Same shape as ``sweep_expiring_tokens`` (``app/workers/meta_token_refresh.py``)
and ``sweep_messenger_backfill``: a cross-tenant maintenance function that owns
its own transactions, registered in ``scheduler_worker.GLOBAL_SWEEPERS``. It
cannot be a ``ScheduledJob`` row because those are seeded per active tenant and
the row this sweep has to catch may belong to a tenant that stopped being active
mid-call.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.modules.voice.application.session_sweeper import (
    DEFAULT_LIMIT,
    SweepOutcome,
    sweep_tenant_sessions,
)

logger = logging.getLogger(__name__)


async def sweep_stale_voice_sessions(
    *,
    now: dt.datetime | None = None,
    stale_after: dt.timedelta | None = None,
    configuring_grace: dt.timedelta | None = None,
    limit: int = DEFAULT_LIMIT,
) -> int:
    """End every abandoned voice session, one RLS-bound transaction per tenant.

    Returns how many rows were ended. One tenant's failure is logged and skipped:
    a shop with a broken row must not stop every other shop's sweep. A tenant's
    transaction is opened, bound, swept and committed as one unit, so the binding
    is live for every read and write the service makes and needs no re-bind.
    """
    from app.core.config import get_settings
    from app.modules.identity.models import Tenant

    # The silence budgets are settings, resolved HERE rather than bound at import: the scheduler
    # calls this with no arguments, and a deployment that needs a longer budget for long holds must
    # not need a code change to get one.
    settings = get_settings()
    if stale_after is None:
        stale_after = dt.timedelta(minutes=settings.voice_sweep_stale_after_minutes)
    if configuring_grace is None:
        configuring_grace = dt.timedelta(minutes=settings.voice_sweep_configuring_grace_minutes)

    # `tenants` carries no RLS, so the enumeration itself needs no context.
    async with SessionLocal() as session:
        tenant_ids = (
            (await session.execute(select(Tenant.id).where(Tenant.is_active))).scalars().all()
        )

    ended = 0
    for tenant_id in tenant_ids:
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    outcome: SweepOutcome = await sweep_tenant_sessions(
                        session,
                        tenant_id,
                        now=now,
                        stale_after=stale_after,
                        configuring_grace=configuring_grace,
                        limit=limit,
                    )
        except Exception:  # noqa: BLE001 - one shop must never stop the sweep
            logger.exception("voice.session_sweep_failed tenant=%s", tenant_id)
            continue
        ended += outcome.ended
    return ended
