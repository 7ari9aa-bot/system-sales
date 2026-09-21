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

import secrets as py_secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.service import NotificationService
from app.modules.platform.models import AuditLog

# A capability token is short-lived: 15 minutes is enough for a human to
# perform the emergency action, and short enough that a leaked token is
# useless after the window.
CAPABILITY_TTL_MINUTES = 15

# In-process capability registry. In production this would be Redis; for
# now the process-local dict is sufficient because the API is stateless and
# the token is validated on the same request that consumes it (or the next
# request within the same process).
_capabilities: dict[str, _Capability] = {}


@dataclass(slots=True, frozen=True)
class _Capability:
    token: str
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: str
    reason: str
    expires_at: datetime


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
) -> str:
    """Record a break-glass event and issue a short-lived capability token.

    Returns the capability token — pass it to the endpoint that accepts
    break-glass. The token is valid for CAPABILITY_TTL_MINUTES.
    """
    if not reason or len(reason.strip()) < 10:
        raise ValueError("break-glass requires a reason of at least 10 characters")

    # 1. Record the audit event — this is the paper trail.
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
    await session.flush()

    # 2. Issue a capability token
    token = py_secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=CAPABILITY_TTL_MINUTES)
    _capabilities[token] = _Capability(
        token=token,
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        expires_at=expires,
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


def validate_capability(
    token: str,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
) -> bool:
    """Check if a capability token is valid for the given action.

    The token is consumed (deleted) after a successful validation — it is
    one-shot, not a session.
    """
    cap = _capabilities.get(token)
    if cap is None:
        return False
    if cap.expires_at < datetime.now(UTC):
        _capabilities.pop(token, None)
        return False
    if cap.tenant_id != tenant_id or cap.user_id != user_id or cap.action != action:
        return False
    # Consume the token
    _capabilities.pop(token, None)
    return True
