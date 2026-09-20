"""Spec §67 — the canonical writer for the platform security-event trail.

Every security-relevant action lands exactly one row in `security_events`. The
row is written on its OWN short-lived transaction so it survives a caller that
raises straight afterwards and rolls the request transaction back — a failed
login is the original case, and the §67 trail was silently empty without it.

RLS: `security_events` is ENABLE + FORCE ROW LEVEL SECURITY with the policy
``tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id')``. A
TENANT-scoped row is therefore rejected unless the tenant GUC is bound on the
writing transaction, so this writer binds it when (and only when) a tenant_id is
given. Pre-auth writers (login failure) pass ``tenant_id=None`` and are allowed
by the NULL branch without any context.

Redaction: callers pass the minimum that answers "who did what" — an event type,
an actor id, a tenant id and coarse details. Secrets, tokens, passwords and full
PII must never be placed in ``details``; use a coarse proxy (e.g. an email
domain) when a human-readable hint is needed.
"""

from __future__ import annotations

import logging
import uuid

from app.core.db import bind_tenant

logger = logging.getLogger(__name__)


async def record_security_event(
    event_type: str,
    *,
    details: dict | None = None,
    ip: str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Persist one §67 security event. Never raises.

    Losing an audit row must not turn a clean 401 into a 500, so failures are
    logged and swallowed — the caller's own error (if any) still propagates.
    """
    # Imported lazily: `app.core.db.SessionLocal` resolves through PEP 562 and
    # builds the engine on first access, which must not happen at import time.
    from app.core.db import SessionLocal
    from app.modules.platform.models import SecurityEvent

    try:
        async with SessionLocal() as session:
            async with session.begin():
                if tenant_id is not None:
                    # FORCE RLS: without this the WITH CHECK rejects a
                    # tenant-scoped row (and the event would vanish silently).
                    await bind_tenant(session, tenant_id)
                session.add(
                    SecurityEvent(
                        event_type=event_type,
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                        details=details or {},
                        ip=ip,
                    )
                )
    except Exception:  # noqa: BLE001 — auditing must not break the action it audits
        logger.warning("security_event.write_failed type=%s", event_type, exc_info=True)
