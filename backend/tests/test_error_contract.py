"""Unified error-contract guard (docs/CONTRACT_AUDIT.md finding 4).

Every 4xx/5xx the app emits must carry the v2 envelope::

    {"error": {"code": ..., "message": ..., "retryable": bool, "request_id": ...}}

built by ``app.core.errors.build_error_body``. The defect this pins: the
contract was defined once and bypassed by four writers in three shapes — a
``{"detail": ...}`` body for the 429 rate limiter (both the denial and the
Redis-outage/auth path) and for the 403 ``PermissionError`` handler, a
hand-built ``{"error": {...}}`` in the body-size middleware, and a dead
``DomainError.to_dict()`` variant. Because ``frontend/src/lib/api.ts`` reads
``body?.error?.message ?? body?.detail`` and ``retryable`` drives the
login/signup retry UX, a bypass degrades a real browser response.

DB-free: the body cap rejects BEFORE the route runs, the rate limiter is driven
with fakeredis, and the 403 handler is exercised through the real wiring — so
the whole guard runs locally (``ENVIRONMENT=local pytest tests/test_error_contract.py``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import middleware as mw
from app.core.errors import DomainError
from app.core.middleware import RateLimitMiddleware
from app.core.security import create_access_token
from app.main import _exception_handlers, _RequestIDMiddleware, create_app

ORDERS = "/api/v1/orders"


def _envelope(body: dict[str, Any], *, retryable: bool | None = None) -> dict[str, Any]:
    """Assert the unified error contract and return its ``error`` object.

    Asserts the envelope itself, ``code`` and ``message`` are non-empty, and
    ``retryable`` is a real bool; ``request_id`` must be present (it may be
    ``None`` only when no request id was ever established).
    """
    error = body.get("error")
    assert isinstance(error, dict), f"missing unified error envelope: {body!r}"
    assert isinstance(error.get("code"), str) and error["code"], body
    assert isinstance(error.get("message"), str) and error["message"], body
    assert isinstance(error.get("retryable"), bool), body
    assert "request_id" in error, body
    if retryable is not None:
        assert error["retryable"] is retryable, body
    return error


# ---------------------------------------------------------------------------
# 413 — BodySizeLimitMiddleware (pure ASGI, emitted before the route runs)
# ---------------------------------------------------------------------------


async def test_body_limit_413_uses_the_contract() -> None:
    """Driven through the REAL app so the request id round-trips.

    An oversized declared ``Content-Length`` is refused by the body cap before
    any route (or the DB) is touched, which is exactly why this stays DB-free.
    """
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            ORDERS,
            content=b"x" * (mw.MAX_BODY_BYTES + 1),
            headers={"x-request-id": "req-413"},
        )

    assert response.status_code == 413
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "payload_too_large"
    assert error["request_id"] == "req-413"


async def test_body_limit_413_keeps_cors_headers_for_the_browser() -> None:
    """The body cap sits INSIDE CORS, so a 413 still carries ``ACAO``.

    Pins the middleware-ordering invariant called out in ``app.main``: moving
    the cap outside CORS would turn the browser's readable 413 into an opaque
    CORS failure.
    """
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            ORDERS,
            content=b"x" * (mw.MAX_BODY_BYTES + 1),
            headers={"Origin": "https://app.example.test"},
        )

    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# 429 — RateLimitMiddleware (denied tier, Redis outage, last-resort failure)
# ---------------------------------------------------------------------------


def _rate_app(client) -> FastAPI:
    app = FastAPI()

    @app.get(ORDERS)
    async def orders() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, client=client, enabled=True)
    # The real request-id publisher, so ``request_id`` is populated the same way
    # the production stack does it.
    app.add_middleware(_RequestIDMiddleware)
    return app


def _ip_headers(ip: str) -> dict[str, str]:
    # Two hops → the last one is trusted by _client_ip.
    return {"x-forwarded-for": f"10.0.0.1, {ip}"}


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return create_access_token(
        str(user_id), {"tenant_id": str(tenant_id), "role": "owner"}
    )


async def _get(app: FastAPI, *, token: str | None = None, ip: str = "8.8.8.8"):
    headers = _ip_headers(ip)
    headers["x-request-id"] = "req-rl"
    if token:
        headers["authorization"] = f"Bearer {token}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(ORDERS, headers=headers)


async def test_rate_limit_denial_uses_the_contract(monkeypatch) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    tenant_id = uuid.uuid4()

    allowed = await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="8.8.8.1")
    denied = await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="8.8.8.2")

    assert allowed.status_code == 200
    assert denied.status_code == 429
    error = _envelope(denied.json(), retryable=True)
    assert error["code"] == "rate_limit_exceeded"
    assert error["request_id"] == "req-rl"
    # The diagnostic extras the limiter's own tests read stay alongside the
    # envelope; the standard retry hint stays a header.
    assert denied.json()["tier"] == "tenant"
    assert denied.headers["retry-after"]
    await client.aclose()


async def test_auth_bucket_redis_outage_uses_the_contract() -> None:
    class ExplodingRedis:
        async def eval(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("redis down")

    app = _rate_app(ExplodingRedis())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            headers={"x-request-id": "req-auth", **_ip_headers("1.1.1.1")},
        )

    assert response.status_code == 429, "auth stays fail-closed on an outage"
    error = _envelope(response.json(), retryable=True)
    assert error["code"] == "rate_limit_exceeded"
    assert error["request_id"] == "req-auth"


async def test_rate_limiter_internal_failure_uses_the_contract(monkeypatch) -> None:
    """The last-resort 429 (an unexpected limiter bug) must not leak a shape."""

    async def _boom(self, tiers):  # noqa: ANN001
        raise RuntimeError("unexpected limiter bug")

    monkeypatch.setattr(mw.LayeredRateLimiter, "check", _boom)
    app = _rate_app(FakeRedis(decode_responses=True))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            headers={"x-request-id": "req-bug", **_ip_headers("2.2.2.2")},
        )

    assert response.status_code == 429
    error = _envelope(response.json(), retryable=True)
    assert error["request_id"] == "req-bug"


# ---------------------------------------------------------------------------
# 403 — the PermissionError handler in app.main
# ---------------------------------------------------------------------------


async def test_permission_error_403_uses_the_contract() -> None:
    app = FastAPI()
    _exception_handlers(app)  # the REAL handler registration
    app.add_middleware(_RequestIDMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise PermissionError("nope")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/boom", headers={"x-request-id": "req-403"})

    assert response.status_code == 403
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "permission_denied"
    assert error["request_id"] == "req-403"


# ---------------------------------------------------------------------------
# DomainError — the reference writer (regression pin)
# ---------------------------------------------------------------------------


async def test_domain_error_404_uses_the_contract() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/webhooks/definitely-not-a-channel",
            headers={"x-request-id": "req-404"},
        )

    assert response.status_code == 404
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "not_found"
    assert error["request_id"] == "req-404"


# ---------------------------------------------------------------------------
# The fifth (dead) variant must not come back
# ---------------------------------------------------------------------------


def test_domain_error_has_no_dead_to_dict_variant() -> None:
    """``to_dict`` emitted ``{code, message, details}`` and had no ``app/``
    caller — a fourth shape waiting to be adopted. It is deleted."""
    assert not hasattr(DomainError, "to_dict")
