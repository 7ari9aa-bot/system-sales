"""Rate limiting middleware — layered per-IP / tenant / user / endpoint.

- Route buckets are matched against the path AFTER the /api/v1 prefix
  (all routes are mounted under it — matching the raw path silently put
  auth/webchat/webhooks in the generic bucket).
- Proxy-aware client IP: X-Forwarded-For is trusted only down to the
  configured trusted-proxy depth (config.TRUSTED_PROXY_COUNT, default 1).
  Each trusted proxy APPENDS its peer, so the real client sits exactly N
  entries from the RIGHT of the chain; anything further left is
  attacker-injectable, and a chain shorter than N carries no trusted
  signature at all — the socket peer wins in both cases. Taking the LAST
  entry (the old rule) keyed every user behind a proxy chain (Cloudflare →
  Vercel → app) to the inner proxy's edge IP and mass-throttled them.
- §25 layered limits: the IP tier (above) is joined by a TENANT tier, a USER
  tier, and an ENDPOINT tier. Each tier has its own Redis key, so one tenant
  can never exhaust another's budget. All tiers are checked in a single
  atomic Lua call (ratelimit.LayeredRateLimiter), so a request denied at one
  tier does not consume capacity at the others.
- Atomic multi-key Lua replaces the previous single-key INCR+PEXPIRE: the
  previous INCR/EXPIRE pair could leave an immortal counter behind if the
  process died between the two calls, and a fixed window allowed up to 2x the
  limit across a boundary. The sliding window has neither problem.
- The STRICT auth bucket (brute-force protection, fail CLOSED when Redis is
  unavailable) covers the credential-granting /auth/* actions — login,
  register, password-reset, mfa-verify, switch-tenant. The session-surface
  endpoints (me / refresh / logout) get a lighter bucket and fail OPEN: a
  user refreshing a token must not compete with an attacker guessing
  passwords for the same budget. Everything else fails open.
- §144: behind the rate tiers sits an in-process per-tenant CONCURRENCY gate
  (tenancy.TenantConcurrencyGovernor) for signature-verified tenants: at-capacity
  requests queue up to the tenant queue depth, then get 429 tier="concurrency".
  It is Redis-free on purpose — it keeps providing backpressure during exactly
  the outages the rate limiter fails open through.
- The tenant/user tiers are derived from the SIGNATURE-VERIFIED access token
  (Bearer header or the HttpOnly access cookie) here, at the edge, rather
  than waiting for the auth dependency — the dependency runs inside the
  route, after this middleware, so it is too late to key a bucket. Only
  ``type == "access"`` tokens qualify: a visitor or refresh token must not
  key the tenant/user tiers (audit finding 6). Decoding is used ONLY for
  keying; authorization still happens in the route's dependency, and an
  invalid token simply falls back to the IP-only tiers. A forged token
  cannot help an attacker.

This module also carries the two edge-hardening middlewares that must run
before the app sees a request: BodySizeLimitMiddleware (S5) and
SecurityHeadersMiddleware (S13).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import (
    DomainError,
    PayloadTooLargeError,
    RateLimitExceededError,
    build_error_body,
    request_id_contextvar,
)
from app.core.ratelimit import LayeredRateLimiter, TierLimit
from app.core.redis import get_redis
from app.core.security import decode_token
from app.core.tenancy import TenantBusyError, TenantConcurrencyGovernor

EXEMPT_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json"}
AUTH_LIMIT = 10          # per window, per IP — credential-granting /auth/* actions
# Session-surface /auth/* endpoints (me / refresh / logout): still bounded, but
# a user refreshing a token or checking who they are must not compete with an
# attacker brute-forcing login — so they do NOT share the strict bucket and do
# NOT fail closed on a Redis outage.
AUTH_SESSION_LIMIT = 60
DEFAULT_LIMIT = 300      # per window, per IP — everything else
PUBLIC_LIMIT = 120       # per window, per IP — webchat/webhook ingress
API_PREFIX = "/api/v1"

# /auth/* subpaths that hand out or rotate credentials. EVERYTHING under
# /auth/ used to share one strict bucket, so a dashboard's routine me/refresh
# polling burned the same budget an attacker was trying to exhaust and locked
# legitimate users out of the endpoints that actually matter.
_AUTH_SESSION_PATHS = frozenset({"/auth/me", "/auth/refresh", "/auth/logout"})

# §25 — layered ceilings on top of the per-IP buckets. These are deliberately
# generous: they are blast-radius caps for a noisy or compromised caller, not
# fairness quotas. Kept as constants because config.py is owned by another
# workstream; they should move to Settings.
TENANT_LIMIT = 3000      # per window, across a whole tenant
USER_LIMIT = 600         # per window, per authenticated user
ENDPOINT_LIMIT = 120     # per window, per caller per route shape

# Generous for JSON APIs (the largest legitimate body is a webhook batch) but
# far below what it takes to exhaust a worker's memory.
MAX_BODY_BYTES = 1_048_576  # 1 MiB

# Product images are sent as raw binary, so this is also the exact file limit.
MAX_PRODUCT_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_PRODUCT_IMAGE_UPLOAD_PATH = re.compile(r"^/products/[0-9a-fA-F-]{36}/images/upload$")

# A path segment that looks like an id (uuid or integer) is collapsed so the
# endpoint tier keys a route shape, not one key per row.
_ID_SEGMENT = re.compile(r"^[0-9a-fA-F-]{16,}$|^\d+$")


def _client_ip(
    request: Request, *, trusted_proxy_count: int | None = None
) -> str:
    """Client IP that an attacker cannot freely rotate.

    Each of the TRUSTED_PROXY_COUNT proxies in front of this process APPENDS
    the peer it received the connection from, so the chain is::

        [attacker-injectable prefix ..., real-client, P1 ... P(N-1)]

    and the real client sits exactly N entries from the RIGHT. Anything
    further left was injected before the first trusted proxy saw the request;
    a chain SHORTER than N carries no trusted signature at all. In both cases
    the socket peer wins.

    Taking the LAST entry (the previous behaviour) keyed every user behind a
    proxy CHAIN (e.g. Cloudflare → Vercel → app) to the inner proxy's edge IP
    and mass-throttled them; TRUSTED_PROXY_COUNT selects the correct hop.
    ``trusted_proxy_count`` overrides the setting (test injection point).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        trusted = (
            get_settings().trusted_proxy_count
            if trusted_proxy_count is None
            else trusted_proxy_count
        )
        if trusted >= 1:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if len(hops) >= trusted and hops[-trusted]:
                return hops[-trusted]
    return request.client.host if request.client else "unknown"


def _bucket_for(path: str) -> tuple[str, int]:
    """Classify by the path relative to the /api/v1 mount point."""
    if path.startswith(API_PREFIX):
        path = path[len(API_PREFIX):]
    if path.startswith("/auth/"):
        # me/refresh/logout are session maintenance, not credential entry
        # points — a lighter bucket keeps routine dashboard traffic from
        # competing with a brute-force attempt for the strict budget.
        if path in _AUTH_SESSION_PATHS:
            return "auth_session", AUTH_SESSION_LIMIT
        return "auth", AUTH_LIMIT
    if path.startswith("/webchat/") or path.startswith("/webhooks/"):
        return "public", PUBLIC_LIMIT
    return "api", DEFAULT_LIMIT


@dataclass(frozen=True, slots=True)
class _Principal:
    user_id: str | None = None
    tenant_id: str | None = None


def _principal_from_request(request: Request) -> _Principal:
    """Signature-verified identity claims for bucket keying only.

    Never an authorization decision (see the module docstring): a missing or
    invalid token yields an empty principal and the IP-only tiers.

    Audit finding 6, both halves:
    - ONLY ``type == "access"`` tokens may key the tenant/user tiers. The
      webchat visitor token carries ``sub`` and ``tenant_id`` too — accepting
      any signed type let a VISITOR exhaust a victim tenant's limits by
      presenting a perfectly valid visitor token as a Bearer header.
    - The cookie-authenticated path (the dashboard's HttpOnly delivery) is
      keyed the same as Bearer: without the fallback, every cookie request
      escaped the tenant/user tiers entirely and burned only its IP budget.
    """
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        from app.modules.identity import cookies

        token = request.cookies.get(cookies.ACCESS_COOKIE)
    if not token:
        return _Principal()
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 — expired/forged token is expected here
        return _Principal()
    if payload.get("type") != "access":
        return _Principal()
    return _Principal(
        user_id=payload.get("sub"), tenant_id=payload.get("tenant_id")
    )


def _endpoint_key(path: str) -> str:
    if path.startswith(API_PREFIX):
        path = path[len(API_PREFIX):]
    parts = [
        ":id" if _ID_SEGMENT.match(segment) else segment
        for segment in path.split("/")
        if segment
    ]
    return "/" + "/".join(parts[:4])


def _tiers_for(
    request: Request, bucket: str, ip_limit: int, principal: _Principal
) -> list[TierLimit]:
    """Build the layered buckets for one request.

    Order determines which tier is reported when several are over budget.
    """
    ip = _client_ip(request)
    tiers = [
        TierLimit(
            "ip",
            f"{bucket}:{ip}",
            ip_limit,
            # Brute-force protection must survive a Redis outage.
            fail_closed=bucket == "auth",
        )
    ]
    owner = principal.tenant_id or ip
    tiers.append(
        TierLimit("endpoint", f"{_endpoint_key(request.url.path)}:{owner}", ENDPOINT_LIMIT)
    )
    if principal.tenant_id:
        tiers.append(TierLimit("tenant", principal.tenant_id, TENANT_LIMIT))
    if principal.user_id:
        tiers.append(TierLimit("user", principal.user_id, USER_LIMIT))
    return tiers


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        limit: int | None = None,
        window_seconds: int = 60,
        client=None,
        enabled: bool | None = None,
        governor: TenantConcurrencyGovernor | None = None,
    ) -> None:
        super().__init__(app)
        self.limit = limit or DEFAULT_LIMIT
        self.window = window_seconds
        # Disabled only when ENVIRONMENT is exactly "test". NOTE: the default
        # is "local" and CI does not set ENVIRONMENT either, so in practice
        # this limiter is ENABLED during local and CI test runs. That is fine
        # where Redis is available (CI runs a Redis service) and harmless where
        # it is not (throughput tiers fail open) — but an auth-bucket request
        # with Redis down WILL get a 429, by design.
        self.enabled = (
            get_settings().environment != "test" if enabled is None else enabled
        )
        self._client = client  # injectable for tests; lazily defaults to Redis
        self._limiter: LayeredRateLimiter | None = None
        # §144: per-tenant in-flight cap. Redis-free by design — it keeps
        # enforcing backpressure during the outages the limiter fails open
        # through. Shared across the middleware instance (one per process).
        self._governor = governor or TenantConcurrencyGovernor()

    def _limiter_for(self) -> LayeredRateLimiter:
        if self._limiter is None:
            self._limiter = LayeredRateLimiter(
                self._client or get_redis(), window_seconds=self.window
            )
        return self._limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS or not self.enabled:
            return await call_next(request)

        bucket, limit = _bucket_for(request.url.path)
        principal = _principal_from_request(request)
        tiers = _tiers_for(request, bucket, limit, principal)
        try:
            result = await self._limiter_for().check(tiers)
        except Exception:
            # LayeredRateLimiter.check already applies the per-tier policy on a
            # Redis outage; this is a last-resort guard so an unexpected bug
            # cannot become a 500. Auth stays fail-closed, the rest fails open.
            if bucket == "auth":
                exc = RateLimitExceededError("try again later")
                return JSONResponse(
                    status_code=exc.http_status,
                    content=build_error_body(
                        exc, request_id=request_id_contextvar.get()
                    ),
                )
            return await self._call_with_slot(request, call_next, principal)

        if not result.allowed:
            retry = max(int(result.retry_after_seconds), 1)
            exc = RateLimitExceededError("rate limit exceeded")
            body = build_error_body(exc, request_id=request_id_contextvar.get())
            # ``tier`` / ``retry_after`` stay alongside the contract envelope:
            # they are the only way to tell WHICH bucket denied, and the
            # limiter's own tests read them. The standard ``Retry-After`` header
            # carries the retry hint to ordinary clients.
            body["tier"] = result.denied_tier
            body["retry_after"] = retry
            return JSONResponse(
                status_code=exc.http_status,
                content=body,
                headers={"Retry-After": str(retry)},
            )
        return await self._call_with_slot(request, call_next, principal)

    async def _call_with_slot(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        principal: _Principal,
    ) -> Response:
        """Run the endpoint inside the tenant's §144 concurrency slot.

        Only authenticated tenant traffic is governed — the signature-verified
        principal is the only key that attributes load to a tenant. A full
        queue is refused with the same 429 contract shape as the rate tiers
        (``tier="concurrency"`` names which gate denied); a queued request
        simply waits, which is the point of having a queue at all. The slot
        ALWAYS returns via finally — a raising route must not leak capacity.
        """
        if principal.tenant_id is None:
            return await call_next(request)
        try:
            await self._governor.acquire(principal.tenant_id)
        except TenantBusyError:
            exc = RateLimitExceededError("tenant at capacity, try again shortly")
            body = build_error_body(exc, request_id=request_id_contextvar.get())
            body["tier"] = "concurrency"
            body["retry_after"] = 1
            return JSONResponse(
                status_code=exc.http_status,
                content=body,
                headers={"Retry-After": "1"},
            )
        try:
            return await call_next(request)
        finally:
            self._governor.release(principal.tenant_id)


# ---------------------------------------------------------------------------
# S5 — request body size limit (pure ASGI: must run before the body is read)
# ---------------------------------------------------------------------------


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _emit_error(send, exc: DomainError) -> None:
    """Write an error using the unified contract v2 envelope (app/core/errors).

    Takes a ``DomainError`` so the body is built by ``build_error_body`` — the
    single place that defines the shape — instead of being hand-assembled here.
    """
    body = json.dumps(
        build_error_body(exc, request_id=request_id_contextvar.get())
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": exc.http_status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Reject oversized request bodies with 413 before they are buffered.

    Nothing capped the body anywhere: a single POST could stream unbounded JSON
    straight into a JSONB column, or simply OOM the process. Content-Length is
    checked first (every normal client sends it); the streaming guard then
    covers chunked uploads that declare no length at all.
    """

    def __init__(self, app, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        route_path = scope.get("path", "")
        if route_path.startswith(API_PREFIX):
            route_path = route_path[len(API_PREFIX):]
        max_bytes = self.max_bytes
        if (
            scope.get("method") == "POST"
            and _PRODUCT_IMAGE_UPLOAD_PATH.fullmatch(route_path)
        ):
            max_bytes = MAX_PRODUCT_IMAGE_UPLOAD_BYTES

        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                oversized = int(declared) > max_bytes
            except ValueError:
                oversized = True  # unparsable length → refuse, do not guess
            if oversized:
                await _emit_error(send, PayloadTooLargeError())
                return

        consumed = 0
        exceeded = False

        async def receive_guarded():
            nonlocal consumed, exceeded
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > max_bytes:
                    exceeded = True
                    # Starve the app of further body instead of buffering it.
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def send_guarded(message):
            nonlocal started
            if exceeded:
                if not started:
                    started = True
                    await _emit_error(send, PayloadTooLargeError())
                return
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, receive_guarded, send_guarded)
        if exceeded and not started:
            await _emit_error(send, PayloadTooLargeError())


# ---------------------------------------------------------------------------
# S13 — baseline security headers
# ---------------------------------------------------------------------------

_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=(), payment=()"),
    # API responses are JSON: nothing should ever be loaded from or framed by
    # them. Keeps a stored-XSS payload from becoming an execution context.
    (
        b"content-security-policy",
        b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    ),
)


class SecurityHeadersMiddleware:
    """Add baseline security headers to every HTTP response.

    The API previously served none. HSTS is only advertised in production (or
    when explicitly requested) — sending it from a plaintext dev origin would
    poison the browser for that host.
    """

    def __init__(self, app, *, hsts: bool | None = None) -> None:
        self.app = app
        self._hsts = hsts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        use_hsts = self._hsts
        if use_hsts is None:
            use_hsts = get_settings().environment == "production"

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                for key, value in _SECURITY_HEADERS:
                    if key not in present:
                        headers.append((key, value))
                if use_hsts and b"strict-transport-security" not in present:
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

