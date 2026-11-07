"""Google OAuth social sign-in routes.

The flow:
1. Frontend links to GET /auth/google/authorize → 302 to Google consent
2. User consents on Google → 302 back to GET /auth/google/callback?code=...
3. Backend exchanges the code for tokens, fetches the profile, and either
   finds or creates the user in our DB, then issues our JWT pair.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token
from app.modules.identity import cookies
from app.modules.identity.deps import DbSession
from app.modules.identity.models import User

router = APIRouter(tags=["auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

_state_store: dict[str, datetime] = {}


def _google_config() -> tuple[str, str]:
    settings = get_settings()
    client_id = settings.google_client_id
    client_secret = settings.google_client_secret
    if not client_id or not client_secret:
        raise ValidationError("Google OAuth is not configured on this server")
    return client_id, client_secret


from app.core.errors import ValidationError  # noqa: E402


def _redirect_uri(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/api/v1/auth/google/callback"


@router.get("/auth/google/authorize")
async def google_authorize(request: Request) -> RedirectResponse:
    """Redirect the browser to Google's consent screen."""
    client_id, _ = _google_config()
    state = secrets.token_urlsafe(32)
    _state_store[state] = datetime.now(UTC)
    cutoff = datetime.now(UTC).timestamp() - 600
    expired = [k for k, v in _state_store.items() if v.timestamp() < cutoff]
    for k in expired:
        _state_store.pop(k, None)

    redirect_uri = _redirect_uri(request)
    params = (
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        "&response_type=code"
        "&scope=openid email profile"
        f"&state={state}"
        "&access_type=offline"
        "&prompt=select_account"
    )
    return RedirectResponse(url=_GOOGLE_AUTH_URL + params, status_code=302)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    session: DbSession = None,  # type: ignore[assignment]
) -> RedirectResponse:
    """Handle Google's redirect: exchange the code, create/find the user, issue JWTs."""
    if error:
        return RedirectResponse(url="/login?error=google_denied", status_code=302)
    if not code or not state or state not in _state_store:
        return RedirectResponse(url="/login?error=google_invalid_state", status_code=302)
    _state_store.pop(state, None)

    client_id, client_secret = _google_config()
    redirect_uri = _redirect_uri(request)

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            return RedirectResponse(url="/login?error=google_token_exchange", status_code=302)
        access_token = token_res.json().get("access_token")
        if not access_token:
            return RedirectResponse(url="/login?error=google_no_token", status_code=302)

        profile_res = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if profile_res.status_code != 200:
            return RedirectResponse(url="/login?error=google_profile", status_code=302)
        profile = profile_res.json()

    email = profile.get("email", "")
    if not email:
        return RedirectResponse(url="/login?error=google_no_email", status_code=302)

    user = (
        await session.execute(sa.select(User).where(sa.func.lower(User.email) == email.lower()))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            password_hash="",
            is_active=True,
            email_verified=profile.get("verified_email", False),
        )
        session.add(user)
        await session.flush()

    if not user.is_active:
        return RedirectResponse(url="/login?error=account_inactive", status_code=302)

    access_jwt = create_access_token(str(user.id), {"auth_version": user.auth_version})
    refresh_jwt = create_refresh_token(str(user.id), {"auth_version": user.auth_version})

    response = RedirectResponse(url="/dashboard", status_code=302)
    cookies.set_auth_cookies(response, access_jwt, refresh_jwt)
    return response
