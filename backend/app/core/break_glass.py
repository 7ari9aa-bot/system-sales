"""Spec §147 — Break-glass support access.

"Break-glass" is the emergency access path: when a human needs to act as a
tenant or perform a privileged action they would not normally have, they
explicitly invoke break-glass, which:

1. Records a SECURITY EVENT in the audit log (not a normal audit row) —
   the action is flagged with `action="break_glass"` and a reason is
   required. The event is ALWAYS written, even if the caller is not
   otherwise authorized (the whole point is that they are NOT).
2. Triggers a notification to the platform admin — so someone knows the
   glass was broken, even if the action was legitimate.
3. Returns a short-lived capability token the caller can use for the
   specific action, not a session.

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
    break-glass. The token is valid for CAPABILITY_TTL_MINUTES.
    """
    if not reason or len(reason.strip()) < 10:
        raise ValueError("break-glass requires a reason of at least 10 characters")

    # 1. Record the paper trail — BOTH the business audit log and the
    # platform §67 security event stream (event_type break_glass).
    log = AuditLog(
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
    session.add(log)
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
    await session.flush()

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
    await client.set(
        _capability_key(token), payload, ex=CAPABILITY_TTL_MINUTES * 60
    )

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
                dedup_key=f"break_glass:{log.id}",
            )

    return token


async def validate_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    redis=None,
) -> bool:
    """Check if a capability token is valid for the given action.

    The token is consumed ATOMICALLY on presentation (GETDEL): it is
    one-shot, and a token presented with mismatched parameters is burned
    rather than left reusable — a capability that escapes its intended
    action must never remain valid. Expiry is enforced by Redis TTL.
    """
    client = redis if redis is not None else get_redis()
    raw = await client.getdel(_capability_key(token))
    return _payload_matches(raw, tenant_id=tenant_id, user_id=user_id, action=action)


async def peek_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    redis=None,
) -> bool:
    """§147 pre-flight: is this capability valid — WITHOUT consuming it?

    ``validate_capability`` is PRESENTATION (atomic GETDEL: one-shot, and a
    mismatched token is burned). A "check whether this works" surface must
    not destroy the token, so the admin-facing validate endpoint uses this
    read-only GET instead; the capability still burns exactly once, at the
    protected action itself.
    """
    client = redis if redis is not None else get_redis()
    raw = await client.get(_capability_key(token))
    return _payload_matches(raw, tenant_id=tenant_id, user_id=user_id, action=action)


def _payload_matches(
    raw, *, tenant_id: uuid.UUID, user_id: uuid.UUID, action: str
) -> bool:
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
