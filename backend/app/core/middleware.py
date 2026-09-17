"""Rate limiting middleware — fixed window in Redis, keyed per client IP.

Fail-open policy: if Redis is unavailable, requests pass (availability over
strict limiting at the edge; services still have per-tenant controls).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.redis import get_redis

EXEMPT_PATHS = {"/healthz", "/readyz", "/docs", "/openapi.json"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int | None = None, window_seconds: int = 60) -> None:
        super().__init__(app)
        settings = get_settings()
        self.limit = limit or 300
        self.window = window_seconds
        self.enabled = settings.environment != "test"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS or not self.enabled:
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:http:{client_ip}:{self.window // 60}min"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.window)
            allowed = count <= self.limit
        except Exception:
            return await call_next(request)  # fail open
        if not allowed:
            ttl = await redis.ttl(key)
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": max(ttl, 1)},
                headers={"Retry-After": str(max(ttl, 1))},
            )
        return await call_next(request)
