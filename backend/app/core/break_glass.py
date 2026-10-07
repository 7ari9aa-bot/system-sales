"""Spec §147 — Break-glass support access.

"Break-glass" is the emergency access path: when a human needs to act as a
tenant or perform a privileged action they would not normally have, they
explicitly invoke break-glass, which:

1. Records a SECURITY EVENT in the audit log (not a normal audit row) —
   the action is flagged with `action="break_glass"` and a reason is
   required. The event is ALWAYS written, even if the caller is not
   otherwise authorized (the whole point is that they are NOT) — the mint
   is fail-closed on the trail write: no paper trail, no capability.
2. Triggers a notification to the platform admin — so someone knows the
   glass was broken, even if the action was legitimate.
3. Returns a short-lived capability token the caller can use for the
   specific action, not a session. The token is consumed ATOMICALLY at the
   protected action (GETDEL): one-shot, race-safe across instances.

Every phase leaves a §67 security event: `break_glass` at mint,
`break_glass_use` when the capability validates, `break_glass_reject` when
a presentation fails — so the trail answers "who broke the glass, who used
it, and who probed with a dead token".

This service does NOT grant any permissions. It records the access event
and notifies. The caller still needs to hold the capability token for the
specific endpoint that accepts break-glass.

Design rule (§147): a break-glass event is NEVER silent. Even if the caller
is the platform admin, the event is recorded — because the purpose is to
leave a paper trail that the glass was broken, regardless of who broke it.
"""

from __future__ import annotations

import json
import secrets as py_secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.modules.notifications.service import NotificationService
from app.modules.platform.models import AuditLog, SecurityEvent

# A capability token is short-lived: 15 minutes is enough for a human to
# perform the emergency action, and short enough that a leaked token is
# useless after the window.
CAPABILITY_TTL_MINUTES = 15

# §59/§147: capabilities live in Redis — shared across API instances and
# surviving restarts, unlike the process-local dict this replaced. The TTL
# is enforced by Redis itself (EX), so an expired token cannot validate
# even if the clock of one instance skews.
_CAPABILITY_PREFIX = "breakglass:cap:"


def _capability_key(token: str) -> str:
    return f"{_CAPABILITY_PREFIX}{token}"


async def _emit_security_event(
    event_type: str,
    *,
    details: dict | None = None,
    ip: str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Emit one §67 security event for a capability outcome (never raises).

    Delegates to the platform writer (own transaction, tenant GUC bound for
    tenant-scoped rows). Function-scoped import: the capability store owns
    its audit boundary without a module-scope coupling to the writer.
    ``details`` carries the scoped action only — never the token itself.
    """
    from app.modules.platform.security_events import record_security_event

    await record_security_event(
        event_type,
        details=details,
        ip=ip,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
    )


async def _persist_trail(
    *,
    audit_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Write the mint's audit + security rows on their OWN transaction.

    The caller's session has the ADMIN's tenant bound for RLS, while the
    rows belong to the TARGET tenant — inserting a tenant-scoped audit or
    security row for another tenant on that session violates the WITH CHECK
    policy and fails exactly when break-glass is used as intended
    (cross-tenant emergency access; verified against the live policies).
    The writer therefore opens a short-lived transaction and binds the
    TARGET tenant GUC itself, the same mechanism ``record_security_event``
    uses for the login-failure path.

    Fail-CLOSED on purpose: §147 says the paper trail is ALWAYS written, so
    a trail write failure must abort the mint rather than hand out an
    unauditable capability. The rows also survive any later rollback of the
    caller's transaction — an audit trail is not a request artifact.
    """
    from app.core.db import SessionLocal, bind_tenant

    async with SessionLocal() as session:
        async with session.begin():
            await bind_tenant(session, tenant_id)
            session.add(
                AuditLog(
                    id=audit_id,
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                    action="break_glass",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    before={"action": action, "reason": reason},
                    after=None,
                    ip=ip,
                    user_agent=user_agent,
                )
            )
            session.add(
                SecurityEvent(
                    event_type="break_glass",
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                    details={
                        "action": action,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "reason": reason,
                    },
                    ip=ip,
                )
            )


async def break_glass(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    ip: str | None = None,
    user_agent: str | None = None,
    admin_user_ids: list[uuid.UUID] | None = None,
    redis=None,
) -> str:
    """Record a break-glass event and issue a short-lived capability token.

    Returns the capability token — pass it to the endpoint that accepts
    break-glass. The token is valid for CAPABILITY_TTL_MINUTES. The mint
    aborts if the audit/security trail cannot be written (fail-closed).
    """
    if not reason or len(reason.strip()) < 10:
        raise ValueError("break-glass requires a reason of at least 10 characters")

    # 1. Record the paper trail — BOTH the business audit log and the
    # platform §67 security event stream (event_type break_glass), on a
    # transaction bound to the TARGET tenant (see _persist_trail). The audit
    # id is minted here so the admin notifications can dedupe against it.
    audit_id = uuid.uuid4()
    await _persist_trail(
        audit_id=audit_id,
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        ip=ip,
        user_agent=user_agent,
    )

    # 2. Issue the capability — Redis, self-expiring, consumable exactly once.
    token = py_secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=CAPABILITY_TTL_MINUTES)
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "reason": reason,
            "expires_at": expires.isoformat(),
        }
    )
    client = redis if redis is not None else get_redis()
    await client.set(_capability_key(token), payload, ex=CAPABILITY_TTL_MINUTES * 60)

    # 3. Notify platform admins (if any admin user ids were provided)
    if admin_user_ids:
        for admin_id in admin_user_ids:
            await NotificationService.create(
                session,
                tenant_id,
                admin_id,
                kind="break_glass",
                title="Break-glass access invoked",
                body=(
                    f"User {user_id} invoked break-glass for {action} "
                    f"on {resource_type}/{resource_id}. Reason: {reason}"
                ),
                action_url=None,
                payload={
                    "actor_user_id": str(user_id),
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "reason": reason,
                },
                dedup_key=f"break_glass:{audit_id}",
            )

    return token


async def validate_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    redis=None,
    record_events: bool = True,
) -> bool:
    """Present a capability at the protected action — one-shot, audited.

    The token is consumed ATOMICALLY on presentation (GETDEL): it is
    one-shot, and a token presented with mismatched parameters is burned
    rather than left reusable — a capability that escapes its intended
    action must never remain valid. Expiry is enforced by Redis TTL.

    Every presentation leaves a §67 event: ``break_glass_use`` when the
    capability validates, ``break_glass_reject`` when it does not (unknown,
    expired, or mismatched) — the reject is auditable even though the token
    is already burned. ``details`` carries the scoped action only, never the
    token value. ``record_events=False`` exists for the pure store-level
    tests; production callers keep the default.
    """
    client = redis if redis is not None else get_redis()
    raw = await client.getdel(_capability_key(token))
    matched = _payload_matches(raw, tenant_id=tenant_id, user_id=user_id, action=action)
    if record_events:
        await _emit_security_event(
            "break_glass_use" if matched else "break_glass_reject",
            details={"action": action, "outcome": "validated" if matched else "rejected"},
            tenant_id=tenant_id,
            actor_user_id=user_id,
        )
    return matched


async def peek_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    redis=None,
    record_events: bool = True,
) -> bool:
    """§147 pre-flight: is this capability valid — WITHOUT consuming it?

    ``validate_capability`` is PRESENTATION (atomic GETDEL: one-shot, and a
    mismatched token is burned). A "check whether this works" surface must
    not destroy the token, so the admin-facing validate endpoint uses this
    read-only GET instead; the capability still burns exactly once, at the
    protected action itself. A FAILED peek is a rejected break-glass attempt
    (dead or mismatched token) and emits ``break_glass_reject``; a successful
    peek stays silent — the use at the protected action is its own event.
    """
    client = redis if redis is not None else get_redis()
    raw = await client.get(_capability_key(token))
    matched = _payload_matches(raw, tenant_id=tenant_id, user_id=user_id, action=action)
    if record_events and not matched:
        await _emit_security_event(
            "break_glass_reject",
            details={"action": action, "outcome": "rejected_preflight"},
            tenant_id=tenant_id,
            actor_user_id=user_id,
        )
    return matched


def _payload_matches(raw, *, tenant_id: uuid.UUID, user_id: uuid.UUID, action: str) -> bool:
    if raw is None:
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    return (
        data.get("tenant_id") == str(tenant_id)
        and data.get("user_id") == str(user_id)
        and data.get("action") == action
    )
