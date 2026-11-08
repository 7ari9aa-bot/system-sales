"""Google OAuth social sign-in routes.

The flow:
1. Frontend links to GET /auth/google/authorize → 302 to Google consent
2. User consents on Google → 302 back to GET /auth/google/callback?code=...
3. Backend exchanges the code for the profile and hands the *proven* address to
   ``AuthService.login_with_google``, which applies the same gates as a password
   login (workspace state, MFA, session recording) and creates a full workspace
   for a brand-new address.

The CSRF ``state`` is a short-lived signed token (not an in-memory dict) so the
flow survives several API instances and restarts. It also carries the two things
that must survive the round trip to Google: where to send the user afterwards
and which website visitor this is (for the owner-console signup funnel).
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.core.security import create_oauth_state_token, decode_token
from app.modules.identity import cookies
from app.modules.identity import service as service
from app.modules.identity.deps import DbSession
from app.modules.identity.routers._deps import _client_meta
from app.modules.identity.service import GoogleMfaRequired

router = APIRouter(tags=["auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_PROVIDER = "google"
_DEFAULT_LANDING = "/dashboard"
_VISITOR_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")


def _google_config() -> tuple[str, str]:
    settings = get_settings()
    return settings.google_client_id, settings.google_client_secret


def _public_base() -> str | None:
    """The configured public origin (API_PUBLIC_BASE_URL), or None if unset or unsafe.

    The callback URL must match, character for character, the one registered in Google Cloud.
    Behind a proxy the Host the app sees is the platform's internal address, and a client-controlled
    Host header is not something to build a redirect from, so the configured origin wins.
    """
    base = (get_settings().api_public_base_url or "").strip().rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return base


def _redirect_uri(request: Request) -> str:
    base = _public_base()
    if base is None:  # local development: no public origin configured
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or request.url.netloc
        base = f"{proto}://{host}"
    return f"{base}/api/v1/auth/google/callback"


def safe_return_to(raw: str | None) -> str:
    """A same-origin path or the dashboard. Mirrors frontend ``safeReturnTo``.

    ``//evil.com`` and ``/\\evil.com`` look like paths but browsers treat them as
    another host, so only a single leading slash with no backslash is allowed.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return _DEFAULT_LANDING
    if any(ord(ch) < 0x20 for ch in raw) or len(raw) > 512:
        return _DEFAULT_LANDING
    return raw


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?error={quote(code)}", status_code=302)


@router.get("/auth/google/authorize")
async def google_authorize(
    request: Request, returnTo: str = "", visitor_id: str = ""
) -> RedirectResponse:
    """Redirect the browser to Google's consent screen."""
    client_id, _ = _google_config()
    if not client_id:
        return _login_error("google_not_configured")

    claims = {
        "provider": _PROVIDER,
        "return_to": safe_return_to(returnTo),
        # Same rule as /auth/register: a malformed id is dropped, never invented.
        "visitor_id": visitor_id if _VISITOR_ID.fullmatch(visitor_id or "") else None,
    }
    state = create_oauth_state_token(_PROVIDER, claims, ttl_seconds=600)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _redirect_uri(request),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return RedirectResponse(url=f"{_GOOGLE_AUTH_URL}?{query}", status_code=302)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    session: DbSession,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Handle Google's redirect: exchange the code, then sign in through the service."""
    if error:
        return _login_error("google_denied")
    if not code or not state:
        return _login_error("google_invalid_state")
    try:
        claims = decode_token(state)
    except Exception:
        return _login_error("google_invalid_state")
    if claims.get("type") != "oauth_state" or claims.get("provider") != _PROVIDER:
        return _login_error("google_invalid_state")

    client_id, client_secret = _google_config()
    if not client_id or not client_secret:
        return _login_error("google_not_configured")

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return _login_error("google_token_exchange")
        access_token = token_res.json().get("access_token")
        if not access_token:
            return _login_error("google_no_token")

        profile_res = await client.get(
            _GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if profile_res.status_code != 200:
            return _login_error("google_profile")
        profile = profile_res.json()

    email = (profile.get("email") or "").strip()
    if not email:
        return _login_error("google_no_email")

    user_agent, ip = _client_meta(request)
    try:
        pair, _user, _tenant_id = await service.AuthService.login_with_google(
            session,
            email=email,
            # OIDC userinfo says `email_verified`; the old v2 endpoint said
            # `verified_email`. Accept only an explicit true.
            email_verified=profile.get("email_verified") is True,
            full_name=(profile.get("name") or None),
            visitor_id=claims.get("visitor_id"),
            user_agent=user_agent,
            ip=ip,
        )
    except GoogleMfaRequired:
        return _login_error("google_mfa_required")
    except PermissionDeniedError as exc:
        reason = str(exc)
        if "not verified" in reason:
            return _login_error("google_email_unverified")
        return _login_error("google_account_unavailable")

    response = RedirectResponse(url=safe_return_to(claims.get("return_to")), status_code=302)
    cookies.set_auth_cookies(response, pair.access_token, pair.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return response
