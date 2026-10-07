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

P5 (docs/GAP_REGISTER.md) filed the remaining four shapes this guard did NOT
yet cover, and measurement confirmed each of them on the current code:

* a request that fails validation answered 422 with FastAPI's default
  ``{"detail": [...]}`` — no envelope, no code, no request id;
* an unmatched route answered 404 with ``{"detail": "Not Found"}`` (and
  ``app/modules/analytics/router.py`` raises the same legacy shape as an
  ``HTTPException``);
* an unhandled crash answered 500 with the ``text/plain`` body
  ``Internal Server Error``, carrying no correlation id at all;
* the ``X-Request-ID`` response header was a DIFFERENT id from the body's
  ``request_id`` — ``RequestLoggingMiddleware`` minted its own — and was
  missing entirely on the 413/429/500 paths, which are emitted outside it.

All four are pinned below, on the real app, with no database: the body cap and
the rate limiter answer before a route runs, the 422 is a pydantic refusal
before the handler body, and the 500 is a route this file adds.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core import middleware as mw
from app.core.errors import DomainError, request_id_contextvar
from app.core.middleware import RateLimitMiddleware
from app.core.security import create_access_token
from app.main import _exception_handlers, _RequestIDMiddleware, create_app

ORDERS = "/api/v1/orders"
#: A public route whose body is validated before the handler runs, so a 422 is
#: reachable on the real graph without a database.
WEBCHAT_INBOUND = "/api/v1/webchat/any-widget-key/messages"
#: A 500 has to come from somewhere; this file owns the only crashing route in
#: the suite and registers it on its own app instance.
CRASH_PATH = "/api/v1/error-contract-probe-crash"


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    return create_access_token(str(user_id), {"tenant_id": str(tenant_id), "role": "owner"})


async def _get(app: FastAPI, *, token: str | None = None, ip: str = "8.8.8.8"):
    headers = _ip_headers(ip)
    headers["x-request-id"] = "req-rl"
    if token:
        headers["authorization"] = f"Bearer {token}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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


# ---------------------------------------------------------------------------
# P5 — the shapes the guard did not cover: 422, legacy 404, unhandled 500
# ---------------------------------------------------------------------------


def _crashing_app() -> FastAPI:
    """The real app, plus the one route that raises a non-domain error.

    A 500 cannot be provoked from a shipped route without a database (or a
    bug), so the probe route is registered here — every layer that matters
    (middleware stack, exception handlers, request-id publisher) is production.
    """
    app = create_app()

    async def crash() -> None:
        raise RuntimeError("boom — an unhandled programming error")

    app.get(CRASH_PATH)(crash)
    return app


async def _real_request(method: str, path: str, **kwargs):
    """One call against the real graph; a 500 must not raise into the test."""
    app = _crashing_app() if path == CRASH_PATH else create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


async def test_request_validation_422_uses_the_contract() -> None:
    """A pydantic refusal used to answer in FastAPI's own shape.

    ``RequestValidationError`` had no handler, so the caller got
    ``{"detail": [...]}``: no code to switch on, no ``retryable``, no
    correlation id — the one 4xx a client hits most often.
    """
    response = await _real_request("POST", WEBCHAT_INBOUND, json={})

    assert response.status_code == 422, response.text
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "validation_error"
    # The message has to say WHICH field and WHAT is wrong, not just "invalid".
    assert "body" in error["message"], error["message"]
    assert error["request_id"]


async def test_request_validation_422_keeps_the_field_list() -> None:
    """``detail`` stays readable: it is a list of ``{loc, msg}`` entries.

    Two real consumers read it — ``frontend/src/lib/api.ts`` falls back to
    ``body?.detail`` and ``tests/test_analytics_window_binding.py`` flattens
    ``detail`` to name the offending window edge — so the canonical envelope is
    ADDED to it, not swapped for it.
    """
    response = await _real_request("POST", WEBCHAT_INBOUND, json={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert {"loc", "msg"} <= set(detail[0]), detail


async def test_unmatched_route_404_uses_the_contract() -> None:
    """The framework's own 404 (no route matched) was ``{"detail\": \"Not Found\"}``.

    A domain ``NotFoundError`` already answered in the envelope, so the SAME
    status reached a client in two bodies depending on whether the path existed.
    """
    response = await _real_request("GET", "/api/v1/no/such/route/here")

    assert response.status_code == 404, response.text
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "not_found"
    assert error["request_id"]
    # Legacy key kept: it is what a ``{"detail": "Not Found"}`` reader expects.
    assert response.json()["detail"] == "Not Found"


async def test_http_exception_422_from_a_route_uses_the_contract() -> None:
    """A route that raises ``HTTPException`` must not answer in the legacy body.

    ``app/modules/analytics/router.py`` deliberately raises 422 with a FastAPI
    ``{loc, msg}`` list so a client reads it like any other 422 — the envelope
    now agrees with that, and the list survives underneath ``detail``.
    """
    app = FastAPI()
    _exception_handlers(app)
    app.add_middleware(_RequestIDMiddleware)

    @app.get("/legacy-422")
    async def legacy() -> None:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["query", "since"],
                    "msg": "Value error, naive",
                }
            ],
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/legacy-422", headers={"x-request-id": "req-httpexc"})

    assert response.status_code == 422, response.text
    error = _envelope(response.json(), retryable=False)
    assert error["code"] == "validation_error"
    assert "query.since" in error["message"], error["message"]
    assert error["request_id"] == "req-httpexc"
    assert response.json()["detail"][0]["loc"] == ["query", "since"]


async def test_unhandled_crash_500_uses_the_contract() -> None:
    """Starlette's default 500 was ``text/plain`` "Internal Server Error".

    Nothing JSON-parseable, no code, no correlation id — the one failure a
    client most needs an id for, because that id is what an operator greps logs
    by. It must also not leak the exception's own text.
    """
    response = await _real_request("GET", CRASH_PATH)

    assert response.status_code == 500, response.text
    error = _envelope(response.json(), retryable=True)
    assert error["code"] == "internal_error"
    assert "boom" not in error["message"], "an unhandled error must not leak"
    assert error["request_id"]


# ---------------------------------------------------------------------------
# P5 — the correlation id in the body IS the id in the response header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        pytest.param("POST", ORDERS, {"content": b"x" * (mw.MAX_BODY_BYTES + 1)}, id="413-cap"),
        pytest.param("POST", WEBCHAT_INBOUND, {"json": {}}, id="422-validation"),
        pytest.param("GET", "/api/v1/webhooks/definitely-not-a-channel", {}, id="404-domain"),
        pytest.param("GET", "/api/v1/no/such/route/here", {}, id="404-unmatched"),
        pytest.param("GET", CRASH_PATH, {}, id="500-crash"),
    ],
)
async def test_error_response_header_matches_the_body_request_id(
    method: str, path: str, kwargs: dict
) -> None:
    """One id per request, in the header AND in the body.

    ``RequestLoggingMiddleware`` generated a second, independent id for the
    ``X-Request-ID`` header, and the 413/429/500 responses are written outside
    it — so they carried no header at all. A client that reports the header it
    was given and a support engineer searching the body's id were looking at two
    different requests.
    """
    response = await _real_request(method, path, **kwargs)

    assert response.status_code in (404, 413, 422, 500)
    body = response.json()
    _envelope(body)
    header = response.headers.get("x-request-id")
    assert header, f"{path}: the error response carries no correlation header"
    assert header == body["error"]["request_id"], (header, body["error"]["request_id"])


async def test_rate_limit_429_header_matches_the_body_request_id(monkeypatch) -> None:
    """The 429 is written by the limiter, which sits OUTSIDE the logging
    middleware that used to own the header — so it never had one."""
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1)
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)

    first = await _get(app)
    second = await _get(app)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["x-request-id"] == second.json()["error"]["request_id"]
    await client.aclose()


async def test_untrusted_request_id_is_replaced_in_both_copies() -> None:
    """A client-supplied id the edge refuses must not survive in the header.

    ``_trusted_trace_id`` rejects an over-long id so it cannot land in the
    String(64) audit columns; the header used to echo the raw client value
    anyway, so the pair disagreed by construction on exactly the input the
    sanitizer exists for.
    """
    untrusted = "x" * 80
    response = await _real_request(
        "GET",
        "/api/v1/webhooks/definitely-not-a-channel",
        headers={"x-request-id": untrusted},
    )

    body_id = response.json()["error"]["request_id"]
    assert body_id and body_id != untrusted
    assert response.headers["x-request-id"] == body_id


# ---------------------------------------------------------------------------
# P5's class guard — the envelope has exactly one writer
# ---------------------------------------------------------------------------

#: The four keys of the v2 contract. A dict that builds any two of them under
#: an ``error`` key is an envelope, whoever wrote it.
_CONTRACT_KEYS = {"code", "message", "retryable", "request_id"}


def _handbuilt_envelopes(source: str) -> list[int]:
    """Lines where ``source`` assembles an error envelope out of literals.

    Two of the four contract keys under an ``error`` key is an envelope: one key
    alone is a domain payload, and a value that is not a dict literal (a call, a
    variable, a subscript) is a module passing the helper's result along.
    """
    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if not (isinstance(key, ast.Constant) and key.value == "error"):
                continue
            if not isinstance(value, ast.Dict):
                continue
            inner = {k.value for k in value.keys if isinstance(k, ast.Constant)}
            if len(inner & _CONTRACT_KEYS) >= 2:
                offenders.append(node.lineno)
    return offenders


def test_the_envelope_writer_guard_bites_and_does_not_cry_wolf() -> None:
    """The sweep must catch a hand-assembled envelope and ignore everything else.

    A guard that has only ever been run against clean source proves nothing —
    it may be matching nothing at all. So it is run against source that has the
    defect, and against the shapes that merely look like one.
    """
    handbuilt = """
async def handler(exc):
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "bad", "message": str(exc), "retryable": False}},
    )
"""
    # Line 5 is the `content=` line; the literal is the only envelope in the file.
    assert _handbuilt_envelopes(handbuilt) == [5], _handbuilt_envelopes(handbuilt)

    # Reading the envelope is not writing one, and neither is a near-miss key.
    for innocent in (
        'def read(body):\n    return body["error"]["code"]\n',
        'def wrap(msg):\n    return {"error": {"detail": msg}}\n',
        'def other():\n    return {"errors": ["a", "b"]}\n',
        'def passthrough(body):\n    return {"error": body}\n',
        'def ok():\n    return {"items": [{"code": "x", "message": "y"}]}\n',
    ):
        assert _handbuilt_envelopes(innocent) == [], innocent


def test_only_core_errors_writes_the_envelope() -> None:
    """No module outside ``core/errors.py`` hand-assembles the contract body.

    P5 was four shapes because four places each wrote their own ``{"error": …}``
    and none of them had to agree. ``build_error_envelope`` is now the single
    writer and everything else calls through it — this sweep is what keeps that
    from drifting back, and it is a tripwire by design: it passes on arrival,
    and the guard above is what proves it can bite.
    """
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        if path.relative_to(app_dir) == Path("core/errors.py"):
            continue
        offenders.extend(
            f"{path.relative_to(app_dir.parent)}: line {n} writes its own envelope"
            for n in _handbuilt_envelopes(path.read_text(encoding="utf-8"))
        )
    assert not offenders, (
        "the v2 envelope has one writer, app/core/errors.py::build_error_envelope;"
        " call it instead of hand-assembling a fifth shape:\n" + "\n".join(offenders)
    )


async def test_idempotency_replies_answer_in_the_contract() -> None:
    """The fifth writer the sweep found, pinned at the byte level.

    ``IdempotencyMiddleware`` answers a conflict and a store outage by writing
    an ASGI ``http.response.start`` itself — no ``JSONResponse``, no handler
    layer — so it assembled the envelope out of literals and could drift from
    the contract without any of the route-level tests noticing.
    """
    from app.core.idempotency import _emit_error

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    request_id_contextvar.set("req-idem")
    await _emit_error(capture, 409, "conflict", "key reused with a different body")
    await _emit_error(capture, 503, "idempotency_unavailable", "store unavailable")

    start, body = sent[0], sent[1]
    assert start["status"] == 409
    assert (b"content-type", b"application/json") in start["headers"]
    payload = json.loads(body["body"])
    error = _envelope(payload, retryable=False)
    assert error["code"] == "conflict"
    assert error["request_id"] == "req-idem"
    # retryable is the status's rule, not a caller's guess: 409 no, 503 yes.
    assert sent[2]["status"] == 503
    assert _envelope(json.loads(sent[3]["body"]), retryable=True)["code"] == (
        "idempotency_unavailable"
    )
