"""Rate limiting middleware — fixed window in Redis, keyed per client IP.

- Route buckets are matched against the path AFTER the /api/v1 prefix
  (all routes are mounted under it — matching the raw path silently put
  auth/webchat/webhooks in the generic bucket).
- Proxy-aware client IP: the X-Forwarded-For chain is only trusted when it
  carries at least two hops (a proxy appended the peer); a single-hop chain
  is client-controlled, so the socket peer is used instead. This blocks
  per-request key rotation via a spoofed header on direct exposure.
- Atomic INCR+PEXPIRE via Lua — the previous INCR/EXPIRE pair could leave an
  immortal counter behind if the process died between the two calls.
- Auth endpoints get a much tighter bucket (brute-force protection) and fail
  CLOSED when Redis is unavailable; everything else fails open.

This module also carries the two edge-hardening middlewares that must run
before the app sees a request: BodySizeLimitMiddleware (S5) and
SecurityHeadersMiddleware (S13).
"""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.redis import get_redis

EXEMPT_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json"}
AUTH_LIMIT = 10          # per window, per IP — login/register/refresh
DEFAULT_LIMIT = 300      # per window, per IP — everything else
PUBLIC_LIMIT = 120       # per window, per IP — webchat/webhook ingress
API_PREFIX = "/api/v1"

# Generous for JSON APIs (the largest legitimate body is a webhook batch) but
# far below what it takes to exhaust a worker's memory.
MAX_BODY_BYTES = 1_048_576  # 1 MiB

# INCR + PEXPIRE atomically; returns the new counter.
_COUNT_SCRIPT = """
local c = redis.call('INCR', KEYS[1])
if c == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
return c
"""


def _client_ip(request: Request) -> str:
    """Client IP that an attacker cannot freely rotate.

    Behind a proxy chain the proxy APPENDS the real peer to X-Forwarded-For,
    so the LAST entry is trustworthy once the chain has 2+ hops. A 0/1-hop
    chain is fully attacker-controlled (or absent), so the socket peer wins.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= 2 and hops[-1]:
            return hops[-1]
    return request.client.host if request.client else "unknown"


def _bucket_for(path: str) -> tuple[str, int]:
    """Classify by the path relative to the /api/v1 mount point."""
    if path.startswith(API_PREFIX):
        path = path[len(API_PREFIX):]
    if path.startswith("/auth/"):
        return "auth", AUTH_LIMIT
    if path.startswith("/webchat/") or path.startswith("/webhooks/"):
        return "public", PUBLIC_LIMIT
    return "api", DEFAULT_LIMIT


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int | None = None, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit or DEFAULT_LIMIT
        self.window = window_seconds
        self.enabled = get_settings().environment != "test"
        self._count_script = None  # registered lazily on first redis use

    async def _count(self, key: str) -> int:
        redis = get_redis()
        if self._count_script is None:
            self._count_script = redis.register_script(_COUNT_SCRIPT)
        return int(
            await self._count_script(keys=[key], args=[self.window * 1000])
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS or not self.enabled:
            return await call_next(request)

        bucket, limit = _bucket_for(request.url.path)
        client_ip = _client_ip(request)
        key = f"rl:http:{bucket}:{client_ip}"
        try:
            count = await self._count(key)
            allowed = count <= limit
        except Exception:
            # Auth stays fail-closed even when Redis is down (brute-force
            # protection must not vanish with the cache tier).
            if bucket == "auth":
                return JSONResponse(status_code=429, content={"detail": "try again later"})
            return await call_next(request)

        if not allowed:
            try:
                ttl = await get_redis().ttl(key)
            except Exception:
                ttl = self.window
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": max(ttl, 1)},
                headers={"Retry-After": str(max(ttl, 1))},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# S5 — request body size limit (pure ASGI: must run before the body is read)
# ---------------------------------------------------------------------------


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _emit_error(send, status: int, code: str, message: str) -> None:
    """Write an error using the unified contract v2 envelope (app/core/errors)."""
    body = json.dumps(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
                "request_id": None,
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
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

        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                oversized = int(declared) > self.max_bytes
            except ValueError:
                oversized = True  # unparsable length → refuse, do not guess
            if oversized:
                await _emit_error(
                    send, 413, "payload_too_large", "Request body too large"
                )
                return

        consumed = 0
        exceeded = False

        async def receive_guarded():
            nonlocal consumed, exceeded
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
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
                    await _emit_error(
                        send, 413, "payload_too_large", "Request body too large"
                    )
                return
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, receive_guarded, send_guarded)
        if exceeded and not started:
            await _emit_error(send, 413, "payload_too_large", "Request body too large")


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

