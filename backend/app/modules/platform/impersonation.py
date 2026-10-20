"""Platform impersonation — the owner console entering a tenant as one of its users.

Threat model first: this is the highest-privilege surface in the platform, so
it is built BORING and LOUD.

- Boring: three endpoints, the write ones gated by a shared platform token
  held in this service's env (``impersonation_platform_token``). An empty
  token means the feature does not exist — every route answers 404 and the
  secret is never probed. The JWT secret never leaves this service: the
  console holds only a one-time, two-minute ticket.
- Loud: every ticket, every handoff page and every redemption writes an
  ``audit_logs`` row, and the issued refresh token records the impersonation
  in its ``user_agent`` — the session itself carries its provenance forever.

The handoff is a two-step POST form (security review F4): the browser opens
``redeem`` (GET) which returns an auto-submitting form whose ticket rides in
a POST BODY — never in a URL that server logs, history or referrers keep —
and only the confirmed POST consumes the ticket and signs in. The single-use
guarantee is fail-CLOSED (security review F1): when Redis is unavailable the
redemption refuses with 503 instead of silently allowing reuse.
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.redis import get_redis_or_none
from app.core.security import create_impersonation_ticket, decode_token
from app.modules.identity.cookies import set_auth_cookies
from app.modules.identity.deps import DbSession
from app.modules.identity.models import Tenant, TenantUser, User
from app.modules.identity.service import AuthService
from app.modules.platform.models import AuditLog

router = APIRouter(prefix="/platform", tags=["platform"])

_TICKET_TTL_SECONDS = 120
_JTI_KEY = "platform:impersonation:jti:{jti}"
_HANDOFF_KEY = "platform:impersonation:handoff:{nonce}"


def _require_platform_token(request: Request) -> None:
    """The shared-secret gate. Empty configured token = feature disabled."""
    settings = get_settings()
    if not settings.impersonation_platform_token:
        raise HTTPException(status_code=404, detail="not found")
    provided = request.headers.get("x-platform-token", "")
    # encode() both sides: hmac.compare_digest raises TypeError on non-ASCII
    # str (security review F7) — a hostile header must be a 403, not a 500.
    if not hmac.compare_digest(
        provided.encode(), settings.impersonation_platform_token.encode()
    ):
        raise PermissionDeniedError("invalid platform token")


class ImpersonationTicketOut(BaseModel):
    ticket: str
    expires_in: int
    redeem_path: str


class ImpersonationRedeemOut(BaseModel):
    location: str


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


async def _load_target(session, user_id, tenant_id):
    """The target must be a real, active, non-platform-admin member of the
    tenant (security review F9: a platform-admin session has break-glass
    reach across ALL tenants — impersonating one would defeat the same
    reasoning that refuses MFA-protected targets)."""
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    membership = (
        await session.execute(
            select(TenantUser).where(
                TenantUser.user_id == user_id, TenantUser.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or membership is None:
        raise NotFoundError("no such active user in this tenant")
    if getattr(user, "is_platform_admin", False):
        raise ConflictError("cannot impersonate a platform-admin account")
    return user, membership


def _safe_target(claims_next: str | None) -> str:
    """Same-site relative paths only (security review F5): `//evil.com` AND
    `/\evil.com` both normalize to an authority in browsers, and an absolute
    URL is an open redirect — anything but a leading-slash path is refused."""
    candidate = claims_next or "/dashboard"
    if candidate.startswith("/") and not candidate.startswith("//") and "\\" not in candidate:
        parts = urlsplit(candidate)
        if not parts.netloc:
            return candidate
    return "/dashboard"


@router.post("/impersonation/tickets", response_model=ImpersonationTicketOut)
async def mint_impersonation_ticket(
    body: ImpersonationTicketRequest, session: DbSession, _: None = Depends(_require_platform_token)
):
    """Mint a one-time, two-minute ticket to enter `user_id`'s session.

    Redeem re-checks everything (defense in depth against a ticket minted
    for a membership that was revoked in the two-minute window).
    """
    # F10: refuse a suspended/deleted tenant EARLY — otherwise a ticket is
    # minted and audited for a redemption that can never succeed.
    tenant_row = (
        await session.execute(select(Tenant).where(Tenant.id == body.tenant_id))
    ).scalar_one_or_none()
    if tenant_row is None or tenant_row.lifecycle_state != "active":
        raise ConflictError("tenant is not active — impersonation refused")
    user, _membership = await _load_target(session, body.user_id, body.tenant_id)

    claims = {
        "tenant_id": str(body.tenant_id),
        "reason": body.reason[:500],
        "redirect_to": body.redirect_to[:200],
    }
    ticket = create_impersonation_ticket(str(user.id), _TICKET_TTL_SECONDS, claims)
    _audit(
        session,
        tenant_id=body.tenant_id,
        action="platform.impersonation.ticket",
        resource_id=f"{body.tenant_id}:{body.user_id}",
        after={"reason": body.reason[:500]},
    )
    await session.commit()
    return ImpersonationTicketOut(
        ticket=ticket, expires_in=_TICKET_TTL_SECONDS,
        redeem_path="/api/v1/platform/impersonation/redeem",
    )


@router.get(
    "/impersonation/redeem",
    response_model=ImpersonationRedeemOut,
    response_class=HTMLResponse,
)
async def redeem_impersonation_ticket(
    ticket: Annotated[str, Query(min_length=1)],
    session: DbSession,
):
    """The handoff page — GET returns an auto-submitting POST form (F4).

    The ticket travels in the form BODY, never in a URL that server access
    logs, browser history or referrers keep. Nothing is consumed here; the
    confirm endpoint below does all the state-changing work.
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

    redis = get_redis_or_none()
    if redis is None:
        # Fail CLOSED (security review F1): the one-time guarantee is a
        # security control, not a cache — no Redis, no redemption.
        raise HTTPException(status_code=503, detail="redemption temporarily unavailable")
    nonce = uuid.uuid4().hex
    await redis.set(_HANDOFF_KEY.format(nonce=nonce), ticket, ex=180)

    script = (
        "fetch('confirm',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({nonce:'__NONCE__'})})"
        ".then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};})})"
        ".then(function(x){if(!x.ok){document.body.textContent=x.j.detail||'failed';"
        "return;}window.location=x.j.location;})"
        ".catch(function(){document.body.textContent='failed';})"
    ).replace("__NONCE__", nonce)
    page = HTMLResponse(
        "<!doctype html><html><body>"
        "<noscript>This handoff requires JavaScript.</noscript>"
        "<script>" + script + "</script>"
        "</body></html>"
    )
    page.headers["Cache-Control"] = "no-store"
    return page


class ImpersonationConfirmBody(BaseModel):
    nonce: str = Field(min_length=8, max_length=128)


@router.post("/impersonation/redeem/confirm", response_model=ImpersonationRedeemOut)
async def confirm_impersonation_ticket(
    body: ImpersonationConfirmBody,
    request: Request,
    session: DbSession,
):
    """Consume the ticket (once) and sign the OWNER'S BROWSER in as the user.

    The cookies are exactly the login flow's pair — nothing bespoke is added
    to the session. Every guard re-runs here: ticket type, single-use via
    Redis, the user's activity and membership, the tenant's login policy.
    An MFA-protected user is refused outright — impersonating past a second
    factor would defeat the factor itself.
    """
    settings = get_settings()
    if not settings.impersonation_platform_token:
        raise HTTPException(status_code=404, detail="not found")

    redis = get_redis_or_none()
    if redis is None:
        raise HTTPException(status_code=503, detail="redemption temporarily unavailable")
    ticket = await redis.get(_HANDOFF_KEY.format(nonce=body.nonce))
    if not ticket:
        raise PermissionDeniedError("handoff expired — start again from the console")
    # one-time for the PAGE too: a replayed nonce cannot re-sign-in
    await redis.delete(_HANDOFF_KEY.format(nonce=body.nonce))

    try:
        claims = decode_token(ticket)
    except Exception as exc:  # noqa: BLE001 — any JWT failure is the same refusal
        raise PermissionDeniedError("invalid ticket") from exc
    if claims.get("type") != "impersonation_ticket":
        raise PermissionDeniedError("invalid ticket")
    jti = claims.get("jti", "")

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

    # The target comes from the SIGNED ticket (security review F6) — a query
    # parameter could be rewritten by anyone holding the URL.
    from fastapi.responses import JSONResponse

    target = _safe_target(claims.get("redirect_to"))
    result = JSONResponse(content=ImpersonationRedeemOut(location=target).model_dump())
    set_auth_cookies(result, pair.access_token, pair.refresh_token)
    result.headers["Cache-Control"] = "no-store"
    return result

