"""HttpOnly cookie delivery for the auth token pair (auth-hardening wave).

The dashboard stores tokens in localStorage; any XSS there is a full account
takeover. These helpers deliver the SAME JWT pair the Bearer flow mints as
HttpOnly cookies — the browser sends them automatically and JavaScript can
never read them — while Bearer keeps working untouched for the desktop
client (ADR-059) and the not-yet-migrated frontend.

Cookie matrix (why each attribute):
- access_token: HttpOnly (unreadable by JS), path=/api/v1 (every
  authenticated API call), max-age = the access TTL — it dies with the JWT.
- refresh_token: HttpOnly, path=/api/v1/auth ONLY — the browser carries it
  to the refresh/logout endpoints and nowhere else.
- csrf_token: NOT HttpOnly (double-submit: JS echoes it as X-CSRF-Token),
  path=/api/v1. Cookie-authenticated mutating requests must present the
  matching header; Bearer requests are exempt (a header cannot be forged
  cross-site).
- SameSite=None + Secure: the dashboard is cross-site (Vercel front,
  Railway back). SameSite=None REQUIRES Secure in real browsers, so Secure
  follows the environment — off for local http, on everywhere else
  (auth_cookie_secure=None means "auto": secure unless ENVIRONMENT=local).
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response

from app.core.config import get_settings

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"

ACCESS_COOKIE_PATH = "/api/v1"
REFRESH_COOKIE_PATH = "/api/v1/auth"
# The csrf value must be readable by document.cookie on EVERY page: the
# session-presence check (and the double-submit echo) run on dashboard
# routes, and a path=/api/v1 cookie is invisible to a /dashboard document.
CSRF_COOKIE_PATH = "/"


def _secure_flag() -> bool:
    s = get_settings()
    if s.auth_cookie_secure is None:
        return s.environment != "local"
    return s.auth_cookie_secure


def _samesite_flag() -> str:
    """SameSite MUST pair with Secure correctly or browsers drop the cookie:
    SameSite=None is refused without Secure (chrome logs `Set-Cookie was
    blocked`), and local runs plain http — so local gets Lax (valid: the
    local dashboard is same-origin through the vite proxy), while every
    https deployment (Vercel front, Railway back = true cross-site) gets
    None, the only value that survives cross-site requests."""
    return "none" if _secure_flag() else "lax"


def _common_kwargs(path: str) -> dict:
    return {
        "path": path,
        "secure": _secure_flag(),
        "samesite": _samesite_flag(),
        "httponly": True,
    }


def new_csrf_token() -> str:
    """A per-session double-submit value: cookie + matching header."""
    return secrets.token_urlsafe(32)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> str:
    """Deliver the minted pair as cookies; returns the CSRF token to echo.

    The caller embeds the returned value BOTH as the csrf_token cookie and —
    on the frontend, once it adopts cookies — as the X-CSRF-Token header.
    """
    s = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=s.access_token_ttl_seconds,
        **_common_kwargs(ACCESS_COOKIE_PATH),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=s.refresh_token_ttl_seconds,
        **_common_kwargs(REFRESH_COOKIE_PATH),
    )
    csrf = new_csrf_token()
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=s.refresh_token_ttl_seconds,
        path=CSRF_COOKIE_PATH,
        secure=_secure_flag(),
        samesite=_samesite_flag(),
        httponly=False,  # double-submit: the frontend must read it to echo it
    )
    return csrf


def clear_auth_cookies(response: Response) -> None:
    """Clear the pair with the EXACT attributes they were set with.

    A mismatched path is the classic way delete_cookie silently does nothing
    (the browser matches the expiry cookie by name + path + domain). Secure and
    SameSite ride the same config-driven helpers as the SET path (audit
    finding 6): they are not part of the browser's matching key, but a clear
    cookie that disagrees with how the set one was delivered (Secure/SameSite
    mode) is exactly the kind of half-state that turns into a
    works-in-staging-drops-in-production bug — and some proxies/CDNs normalize
    or refuse Set-Cookie headers whose flags contradict the request scheme.
    One source of truth, both directions.
    """
    response.delete_cookie(
        ACCESS_COOKIE,
        path=ACCESS_COOKIE_PATH,
        secure=_secure_flag(),
        samesite=_samesite_flag(),
    )
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=_secure_flag(),
        samesite=_samesite_flag(),
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path=CSRF_COOKIE_PATH,
        secure=_secure_flag(),
        samesite=_samesite_flag(),
    )


MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def csrf_satisfied(request: Request, *, cookie_authenticated: bool) -> bool:
    """True when the request may proceed under cookie authentication.

    Bearer-authenticated calls are exempt (the Authorization header cannot be
    attached by a cross-site form), and so are safe methods. Cookie calls
    that mutate must present X-CSRF-Token equal to the csrf_token cookie —
    the double-submit check.
    """
    if not cookie_authenticated:
        return True
    if request.method not in MUTATING_METHODS:
        return True
    supplied = request.headers.get("x-csrf-token")
    stored = request.cookies.get(CSRF_COOKIE)
    return bool(supplied and stored and secrets.compare_digest(supplied, stored))
