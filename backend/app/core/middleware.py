"""Rate limiting middleware — fixed window in Redis, keyed per client IP.

- Proxy-aware: uses the forwarded chain's LAST hop (Railway/Vercel terminate
  TLS and forward X-Forwarded-For).
- Auth endpoints get a much tighter bucket (brute-force protection).
- Fail-open for non-auth routes when Redis is unavailable (availability over
  strict limiting at the edge); auth routes fail CLOSED.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.redis import get_redis

EXEMPT_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json"}
AUTH_LIMIT = 10          # per window, per IP — login/register/refresh
DEFAULT_LIMIT = 300      # per window, per IP — everything else


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int | None = None, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit or DEFAULT_LIMIT
        self.window = window_seconds
        self.enabled = get_settings().environment != "test"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS or not self.enabled:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/auth/"):
            bucket, limit = "auth", AUTH_LIMIT
        elif path.startswith("/webchat/") or path.startswith("/webhooks/"):
            bucket, limit = "public", 120
        else:
            bucket, limit = "api", self.limit

        client_ip = _client_ip(request)
        key = f"rl:http:{bucket}:{client_ip}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.window)
            allowed = count <= limit
        except Exception:
            # Auth stays fail-closed even when Redis is down (brute-force
            # protection must not vanish with the cache tier).
            if bucket == "auth":
                return JSONResponse(status_code=429, content={"detail": "try again later"})
            return await call_next(request)

        if not allowed:
            ttl = await redis.ttl(key)
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": max(ttl, 1)},
                headers={"Retry-After": str(max(ttl, 1))},
            )
        return await call_next(request)
