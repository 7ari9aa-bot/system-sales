"""Platform impersonation — the owner console entering a tenant as one of its users.

Threat model first: this is the highest-privilege surface in the platform, so
it is built BORING and LOUD.

- Boring: two endpoints, both gated by a shared platform token held in this
  service's env (``impersonation_platform_token``). An empty token means the
  feature does not exist — both routes answer 404 and the secret is never
  probed. The JWT secret never leaves this service: the console holds only a
  one-time, two-minute ticket.
- Loud: every ticket mint and every redemption writes an ``audit_logs`` row,
  and the issued refresh token records the impersonation in its ``user_agent``
  — the session itself carries its provenance forever, not just the entry.

The redeem endpoint is GET on purpose: the console sends the OWNER'S BROWSER
here with the ticket, this service sets the SAME HttpOnly cookie pair the
login flow sets, and the browser lands on the dashboard already signed in.
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.redis import get_redis_or_none
from app.core.security import create_impersonation_ticket, decode_token
from app.modules.identity.cookies import set_auth_cookies
from app.modules.identity.deps import DbSession
from app.modules.identity.models import TenantUser, User
from app.modules.identity.service import AuthService
from app.modules.platform.models import AuditLog

router = APIRouter(prefix="/platform", tags=["platform"])

_TICKET_TTL_SECONDS = 120
_JTI_KEY = "platform:impersonation:jti:{jti}"


def _require_platform_token(request: Request) -> None:
    """The shared-secret gate. Empty configured token = feature disabled."""
    settings = get_settings()
    if not settings.impersonation_platform_token:
        raise HTTPException(status_code=404, detail="not found")
    provided = request.headers.get("x-platform-token", "")
    if not hmac.compare_digest(provided, settings.impersonation_platform_token):
        raise PermissionDeniedError("invalid platform token")


class ImpersonationTicketRequest(BaseModel):
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)
    redirect_to: str = Field(default="/dashboard")


def _audit(session, *, tenant_id, action: str, resource_id: str, after: dict) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,  # the principal is the platform console, not a user
            action=action,
            resource_type="tenant_user",
            resource_id=resource_id,
            after=after,
            user_agent="owner-console",
        )
    )


@router.post("/impersonation/tickets")
async def mint_impersonation_ticket(
    body: ImpersonationTicketRequest, session: DbSession, _: None = Depends(_require_platform_token)
):
    """Mint a one-time, two-minute ticket to enter `user_id`'s session.

    Validates that the user is real, active, and a member of the tenant —
    the ticket is useless for any other combination, and redeem re-checks all
    three (defense in depth against a ticket minted for a membership that
    was revoked in the two-minute window).
    """
    user = (
        await session.execute(select(User).where(User.id == body.user_id))
    ).scalar_one_or_none()
    membership = (
        await session.execute(
            select(TenantUser).where(
                TenantUser.user_id == body.user_id, TenantUser.tenant_id == body.tenant_id
            )
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or membership is None:
        raise NotFoundError("no such active user in this tenant")

    claims = {
        "tenant_id": str(body.tenant_id),
        "reason": body.reason[:500],
        "redirect_to": body.redirect_to[:200],
    }
    ticket = create_impersonation_ticket(str(body.user_id), _TICKET_TTL_SECONDS, claims)
    _audit(
        session,
        tenant_id=body.tenant_id,
        action="platform.impersonation.ticket",
        resource_id=f"{body.tenant_id}:{body.user_id}",
        after={"reason": body.reason[:500]},
    )
    await session.commit()
    return {"ticket": ticket, "expires_in": _TICKET_TTL_SECONDS,
            "redeem_path": "/api/v1/platform/impersonation/redeem"}


@router.get("/impersonation/redeem")
async def redeem_impersonation_ticket(
    request: Request,
    session: DbSession,
    ticket: Annotated[str, Query(min_length=1)],
    next_path: Annotated[str, Query(alias="next")] = "/dashboard",
):
    """Consume a one-time ticket and sign the OWNER'S BROWSER in as the user.

    The cookies are exactly the login flow's pair — nothing bespoke is added
    to the session. Every guard re-runs here: ticket type, single-use via
    Redis, the user's activity, the membership, and the tenant's login
    policy. An MFA-protected user is refused outright — impersonating past a
    second factor would defeat the factor itself.
    """
    settings = get_settings()
    if not settings.impersonation_platform_token:
        raise HTTPException(status_code=404, detail="not found")
    try:
        claims = decode_token(ticket)
    except Exception as exc:  # noqa: BLE001 — any JWT failure is the same refusal
        raise PermissionDeniedError("invalid ticket") from exc
    if claims.get("type") != "impersonation_ticket":
        raise PermissionDeniedError("invalid ticket")
    jti = claims.get("jti", "")

    redis = get_redis_or_none()
    if redis is not None:
        consumed = await redis.set(_JTI_KEY.format(jti=jti), "1", nx=True, ex=600)
        if not consumed:
            raise ConflictError("ticket already used")

    user = (
        await session.execute(select(User).where(User.id == claims.get("sub")))
    ).scalar_one_or_none()
    tenant_id = claims.get("tenant_id")
    membership = (
        await session.execute(
            select(TenantUser).where(
                TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
    ) if user is not None and user.is_active and tenant_id else None
    if user is None or membership is None:
        raise NotFoundError("impersonation target no longer valid")

    from app.core.mfa import is_mfa_enabled

    if await is_mfa_enabled(session, user_id=user.id):
        raise ConflictError("cannot impersonate an MFA-protected account")

    await AuthService._assert_tenant_allows_login(session, tenant_id, user_id=user.id)

    pair = AuthService._issue_pair(
        session,
        user,
        tenant_id,
        user_agent=f"owner-console impersonation (jti {jti[:8]})",
        ip=request.client.host if request.client else None,
    )
    _audit(
        session,
        tenant_id=membership.tenant_id,
        action="platform.impersonation.start",
        resource_id=f"{tenant_id}:{user.id}",
        after={"reason": claims.get("reason", ""), "jti": jti},
    )
    await session.commit()

    # Only same-site relative targets survive the allowlist — an open redirect
    # would turn the ticket into a phishing primitive.
    target = (
        next_path
        if next_path.startswith("/") and not next_path.startswith("//")
        else "/dashboard"
    )
    redirect = RedirectResponse(url=target, status_code=303)
    set_auth_cookies(redirect, pair.access_token, pair.refresh_token)
    return redirect
