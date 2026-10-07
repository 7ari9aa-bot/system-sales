"""Request-integrity tests: idempotent writes (G-14), conditional writes
(G-15) and layered rate limits (§25).

DB-free tests run everywhere; the DB-backed ones use the shared ``db`` /
``tenant_ctx`` fixtures and are skipped locally when no database URL is set.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import middleware as mw
from app.core.errors import ConflictError, ValidationError
from app.core.idempotency import (
    CONFLICT,
    FAILED,
    NEW,
    REPLAY,
    IdempotencyClaim,
    IdempotencyMiddleware,
    IdempotencyService,
    apply_etag,
    apply_versioned_update,
    body_hash,
    etag_for,
    idem_scope,
    parse_if_match,
    require_version,
    should_guard,
)
from app.core.ratelimit import LayeredRateLimiter, TierLimit
from app.core.security import create_access_token, create_visitor_token

ORDERS_PATH = "/api/v1/orders"
ORDERS_BODY = b'{"amount": 10}'
WEBHOOK_ENDPOINTS_PATH = "/api/v1/webhook-endpoints"


# ---------------------------------------------------------------------------
# Idempotency — policy (DB-free)
# ---------------------------------------------------------------------------


def test_should_guard_only_allowlisted_paths() -> None:
    assert should_guard("POST", ORDERS_PATH) is True
    assert should_guard("POST", "/api/v1/orders/abc/payments") is True
    assert should_guard("DELETE", "/api/v1/orders/abc") is True
    # A path that merely shares a prefix is not the allow-listed route.
    assert should_guard("POST", "/api/v1/orders-report") is False
    # Not on the allow-list at all.
    assert should_guard("POST", "/api/v1/customers") is False
    # Package 2.2, closing the gap 2.1 documented: webhook endpoint registration
    # is allow-listed (a bare retry of a lost register response used to mint a
    # SECOND active endpoint + secret), and its sub-paths ride the prefix —
    # while a lookalike prefix stays off the list.
    assert should_guard("POST", "/api/v1/webhook-endpoints") is True
    assert should_guard("POST", "/api/v1/webhook-endpoints/abc/rotate") is True
    assert should_guard("DELETE", "/api/v1/webhook-endpoints/abc") is True
    assert should_guard("POST", "/api/v1/webhook-endpoints-report") is False


def test_should_guard_ignores_read_methods() -> None:
    assert should_guard("GET", ORDERS_PATH) is False
    assert should_guard("HEAD", ORDERS_PATH) is False


def test_idem_scope_is_tenant_scoped_and_fits_the_column() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    scope_a = idem_scope(tenant_a, "POST", ORDERS_PATH)
    scope_b = idem_scope(tenant_b, "POST", ORDERS_PATH)

    assert str(tenant_a) in scope_a
    assert scope_a != scope_b, "two tenants must never share a dedupe scope"
    assert len(scope_a) <= 63, "IdempotencyKey.scope is String(63)"
    # Same request is stable; a different route is distinct.
    assert scope_a == idem_scope(tenant_a, "POST", ORDERS_PATH)
    assert scope_a != idem_scope(tenant_a, "POST", "/api/v1/orders/1/cancel")


def test_idem_scope_anonymous_falls_back_to_ip() -> None:
    assert "ip:1.2.3.4" in idem_scope(None, "POST", ORDERS_PATH, client_ip="1.2.3.4")


def test_body_hash_tracks_the_body() -> None:
    assert body_hash(b"a") == body_hash(b"a")
    assert body_hash(b"a") != body_hash(b"b")


# ---------------------------------------------------------------------------
# Idempotency — middleware (DB-free, fake store)
# ---------------------------------------------------------------------------


class FakeStore:
    """In-memory stand-in for DbIdempotencyStore with the same outcomes.

    Mirrors the real record states (processing / processed / failed) so the
    middleware's 4xx-release and 5xx-terminal behaviour is exercised.
    """

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.completes = 0
        self.fails = 0
        self.releases = 0

    async def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyClaim:
        record = self.records.get((scope, key))
        if record is None:
            self.records[(scope, key)] = {
                "hash": request_hash,
                "status": "processing",
                "response": None,
            }
            return IdempotencyClaim(NEW)
        if record["hash"] != request_hash:
            return IdempotencyClaim(CONFLICT)
        if record["status"] == "failed":
            return IdempotencyClaim(FAILED)
        if record["status"] == "processed" and record["response"] is not None:
            return IdempotencyClaim(REPLAY, record["response"])
        return IdempotencyClaim("in_progress")

    async def complete(
        self, *, scope: str, key: str, status_code: int, body: bytes, content_type: str
    ) -> None:
        self.completes += 1
        record = self.records[(scope, key)]
        record["status"] = "processed"
        record["response"] = {
            "status": status_code,
            "body": base64.b64encode(body).decode(),
            "content_type": content_type,
        }

    async def fail(
        self, *, scope: str, key: str, status_code: int | None = None
    ) -> None:
        self.fails += 1
        record = self.records[(scope, key)]
        record["status"] = "failed"
        record["response"] = None

    async def release(self, *, scope: str, key: str) -> None:
        self.releases += 1
        self.records.pop((scope, key), None)


class ExplodingStore(FakeStore):
    async def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyClaim:
        raise RuntimeError("idempotency store down")


def _endpoint(counter: dict[str, int]):
    async def app(scope, receive, send) -> None:
        # Consume the body exactly as a real route would.
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body"):
                break
        counter["calls"] += 1
        body = json.dumps({"call": counter["calls"]}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 201,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


async def _run(
    app,
    *,
    method: str = "POST",
    path: str = ORDERS_PATH,
    body: bytes = ORDERS_BODY,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "client": ("1.2.3.4", 1234),
        "query_string": b"",
    }
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    response_headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], payload, response_headers


async def test_same_key_replays_first_response_and_runs_effect_once() -> None:
    store = FakeStore()
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=store, enabled=True)
    headers = [(b"idempotency-key", b"key-1")]

    first = await _run(app, headers=headers)
    second = await _run(app, headers=headers)

    assert first[0] == 201 and second[0] == 201
    assert first[1] == second[1], "the retry must return the FIRST response"
    assert counter["calls"] == 1, "the effect must run exactly once"
    assert second[2].get("idempotency-replayed") == "true"


async def test_same_key_different_body_is_rejected() -> None:
    store = FakeStore()
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=store, enabled=True)
    headers = [(b"idempotency-key", b"key-1")]

    await _run(app, headers=headers)
    status, payload, _ = await _run(app, body=b'{"amount": 99}', headers=headers)

    assert status == 409
    assert json.loads(payload)["error"]["code"] == "conflict"
    assert counter["calls"] == 1


async def test_header_is_optional_and_path_must_be_allowlisted() -> None:
    store = FakeStore()
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=store, enabled=True)

    # Allow-listed path, no header → plain pass-through.
    await _run(app, headers=[])
    # Header present but path not allow-listed → plain pass-through.
    await _run(
        app, path="/api/v1/customers", headers=[(b"idempotency-key", b"key-2")]
    )

    assert counter["calls"] == 2
    assert store.completes == 0
    assert store.records == {}


# ---------------------------------------------------------------------------
# Idempotency — webhook endpoint registration (package 2.2 closes the 2.1 gap)
# ---------------------------------------------------------------------------
#
# The documented gap: ``POST /webhook-endpoints`` mints a signing secret, and a
# client that retried a lost register response WITHOUT idempotency protection
# created a SECOND active endpoint — two secrets to rotate, duplicate
# deliveries, no way to tell which one a receiver verifies against. The path is
# on ``IDEMPOTENT_PATHS`` now; these pin the full replay contract on it: same
# key → same response, effect once; same key + different body → 409.


async def test_webhook_endpoint_registration_replays_instead_of_running_twice() -> None:
    """A retried register with the SAME key gets the FIRST response back."""
    store = FakeStore()
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=store, enabled=True)
    headers = [(b"idempotency-key", b"register-key-1")]

    first = await _run(app, path=WEBHOOK_ENDPOINTS_PATH, headers=headers)
    second = await _run(app, path=WEBHOOK_ENDPOINTS_PATH, headers=headers)

    assert first[0] == 201 and second[0] == 201
    assert first[1] == second[1], "the retry must return the FIRST registration"
    assert counter["calls"] == 1, "the register effect must run exactly once"
    assert second[2].get("idempotency-replayed") == "true"


async def test_webhook_endpoint_registration_rejects_a_key_reused_with_a_new_body() -> None:
    """The same key presented with a DIFFERENT endpoint body is a client bug —
    refused, never replayed for the wrong request and never re-registered."""
    store = FakeStore()
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=store, enabled=True)
    headers = [(b"idempotency-key", b"register-key-2")]

    await _run(app, path=WEBHOOK_ENDPOINTS_PATH, headers=headers)
    status, payload, _ = await _run(
        app,
        path=WEBHOOK_ENDPOINTS_PATH,
        body=b'{"url": "https://other.example.test/hook", "events": ["order"]}',
        headers=headers,
    )

    assert status == 409
    assert json.loads(payload)["error"]["code"] == "conflict"
    assert counter["calls"] == 1


async def test_store_outage_fails_closed() -> None:
    counter = {"calls": 0}
    app = IdempotencyMiddleware(_endpoint(counter), store=ExplodingStore(), enabled=True)

    status, payload, _ = await _run(app, headers=[(b"idempotency-key", b"key-3")])

    assert status == 503
    assert json.loads(payload)["error"]["code"] == "idempotency_unavailable"
    assert counter["calls"] == 0, "a write must not proceed when it cannot be recorded"


async def test_5xx_is_terminal_and_a_retry_is_refused() -> None:
    """A 5xx means the outcome is UNKNOWN, not "did not happen".

    The reservation must survive so the retry cannot re-execute an effect that
    may have partially applied (the double-charge case for a non-transactional
    provider call).
    """
    store = FakeStore()
    calls = {"calls": 0}

    async def failing_app(scope, receive, send) -> None:
        calls["calls"] += 1
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"detail":"down"}'})

    app = IdempotencyMiddleware(failing_app, store=store, enabled=True)
    headers = [(b"idempotency-key", b"key-4")]

    first = await _run(app, headers=headers)
    second = await _run(app, headers=headers)

    assert first[0] == 503
    assert second[0] == 409, "an unknown outcome must not be re-executed"
    assert json.loads(second[1])["error"]["code"] == "conflict"
    assert calls["calls"] == 1, "the effect must NOT run a second time"
    assert store.fails == 1
    assert store.releases == 0, "a 5xx must never free the key for re-execution"


async def test_exception_marks_the_key_failed_not_released() -> None:
    """An escaping exception is also an unknown outcome."""
    store = FakeStore()

    async def exploding_app(scope, receive, send) -> None:
        raise RuntimeError("boom")

    app = IdempotencyMiddleware(exploding_app, store=store, enabled=True)
    headers = [(b"idempotency-key", b"key-6")]

    with pytest.raises(RuntimeError):
        await _run(app, headers=headers)

    assert store.fails == 1
    assert store.releases == 0
    retry = await _run(app, headers=headers)
    assert retry[0] == 409


async def test_4xx_releases_the_key_so_a_corrected_retry_can_run() -> None:
    """A client-caused rejection means nothing ran, so the key is free again."""
    store = FakeStore()
    calls = {"calls": 0}

    async def rejecting_then_ok_app(scope, receive, send) -> None:
        calls["calls"] += 1
        # Reject the first attempt, accept the corrected retry.
        status = 422 if calls["calls"] == 1 else 200
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"ok": true}'})

    app = IdempotencyMiddleware(rejecting_then_ok_app, store=store, enabled=True)
    headers = [(b"idempotency-key", b"key-5")]

    first = await _run(app, headers=headers)
    # Same key, corrected body — allowed because the first attempt never ran.
    second = await _run(app, body=b'{"fixed": true}', headers=headers)

    assert first[0] == 422
    assert second[0] == 200, "the key was released, so the corrected retry ran"
    assert calls["calls"] == 2
    assert store.releases == 1
    assert store.fails == 0
    assert store.completes == 1


# ---------------------------------------------------------------------------
# Conditional writes — ETag / If-Match (DB-free)
# ---------------------------------------------------------------------------


def test_etag_roundtrip() -> None:
    assert etag_for(3) == '"3"'
    assert parse_if_match('"3"') == 3
    assert parse_if_match('W/"4"') == 4
    assert parse_if_match('"3", "4"') == 3
    assert parse_if_match("*") is None
    assert parse_if_match(None) is None


def test_malformed_if_match_is_a_client_error() -> None:
    with pytest.raises(ValidationError):
        parse_if_match("not-a-version")


def test_require_version_stale_raises_conflict() -> None:
    with pytest.raises(ConflictError) as exc_info:
        require_version('"2"', 5)
    assert exc_info.value.http_status == 409


def test_require_version_current_or_absent_passes() -> None:
    require_version('"5"', 5)  # current
    require_version(None, 5)  # unconditional


def test_apply_etag_sets_header() -> None:
    from starlette.responses import JSONResponse

    response = apply_etag(JSONResponse({"ok": True}), 7)
    assert response.headers["ETag"] == '"7"'


# ---------------------------------------------------------------------------
# Layered rate limits (DB-free)
# ---------------------------------------------------------------------------


async def test_layered_denial_consumes_no_other_tier_capacity() -> None:
    client = FakeRedis(decode_responses=True)
    limiter = LayeredRateLimiter(client, window_seconds=60, clock=lambda: 1000.0)
    tiers = [TierLimit("tenant", "t", 1), TierLimit("user", "u", 5)]

    assert (await limiter.check(tiers)).allowed is True
    denied = await limiter.check(tiers)
    assert denied.allowed is False and denied.denied_tier == "tenant"

    # The user bucket was charged only once (the denial must not have counted).
    for _ in range(4):
        assert (
            await limiter.check([TierLimit("tenant", "fresh", 100), TierLimit("user", "u", 5)])
        ).allowed is True
    assert (
        await limiter.check([TierLimit("tenant", "fresh2", 100), TierLimit("user", "u", 5)])
    ).allowed is False
    await client.aclose()


async def test_layered_fails_closed_only_for_marked_tiers() -> None:
    class ExplodingRedis:
        async def eval(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("redis down")

    limiter = LayeredRateLimiter(ExplodingRedis(), window_seconds=60)
    closed = await limiter.check([TierLimit("ip", "x", 10, fail_closed=True)])
    assert closed.allowed is False and closed.denied_tier == "ip"

    open_result = await limiter.check([TierLimit("ip", "x", 10)])
    assert open_result.allowed is True


def _rate_app(client, **kwargs) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/orders")
    async def orders() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(mw.RateLimitMiddleware, client=client, enabled=True, **kwargs)
    return app


def _ip_headers(ip: str) -> dict[str, str]:
    # Two hops → the last one is trusted by _client_ip.
    return {"x-forwarded-for": f"10.0.0.1, {ip}"}


async def _get(app: FastAPI, *, token: str | None = None, ip: str = "8.8.8.8"):
    headers = _ip_headers(ip)
    if token:
        headers["authorization"] = f"Bearer {token}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/api/v1/orders", headers=headers)


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return create_access_token(
        str(user_id), {"tenant_id": str(tenant_id), "role": "owner"}
    )


async def test_tenant_tier_refuses_past_its_limit(monkeypatch) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 2)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    tenant_id = uuid.uuid4()

    responses = []
    for i in range(3):
        # Distinct users and IPs so ONLY the tenant tier can deny.
        token = _token(uuid.uuid4(), tenant_id)
        responses.append(await _get(app, token=token, ip=f"8.8.8.{i + 1}"))

    assert [r.status_code for r in responses] == [200, 200, 429]
    assert responses[2].json()["tier"] == "tenant"
    await client.aclose()


async def test_one_tenant_cannot_exhaust_anothers_budget(monkeypatch) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 2)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()

    for i in range(2):
        await _get(app, token=_token(uuid.uuid4(), tenant_a), ip=f"9.9.9.{i + 1}")
    exhausted = await _get(app, token=_token(uuid.uuid4(), tenant_a), ip="9.9.9.9")
    other = await _get(app, token=_token(uuid.uuid4(), tenant_b), ip="9.9.9.9")

    assert exhausted.status_code == 429
    assert other.status_code == 200, "tenant B has its own budget"
    await client.aclose()


async def test_user_tier_refuses_past_its_limit(monkeypatch) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1000)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    monkeypatch.setattr(mw, "USER_LIMIT", 2)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()

    responses = []
    for i in range(3):
        # Distinct IPs so ONLY the user tier can deny.
        responses.append(
            await _get(app, token=_token(user_id, tenant_id), ip=f"7.7.7.{i + 1}")
        )

    assert [r.status_code for r in responses] == [200, 200, 429]
    assert responses[2].json()["tier"] == "user"
    await client.aclose()


async def test_a_visitor_token_never_keys_the_tenant_tier(monkeypatch) -> None:
    """Audit finding 6, half one: the webchat visitor JWT is fully signed and
    carries sub + tenant_id, so a limiter that trusts any decoded payload let a
    VISITOR exhaust a victim tenant's budget by presenting a valid visitor
    token as a Bearer header. Only type=access may key the tenant/user tiers.
    """
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    tenant_id = uuid.uuid4()
    visitor = create_visitor_token("sess-1", str(tenant_id), widget="pk_1")

    # The visitor's own request passes — and charges no tenant tier.
    first = await _get(app, token=visitor, ip="6.6.6.1")
    # A real access token from the SAME tenant still has its full budget.
    second = await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="6.6.6.2")
    exhausted = await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="6.6.6.3")

    assert first.status_code == 200
    assert second.status_code == 200, "the visitor request never charged the tenant tier"
    assert exhausted.status_code == 429
    assert exhausted.json()["tier"] == "tenant"
    await client.aclose()


async def test_cookie_authenticated_requests_still_key_the_tenant_tier(monkeypatch) -> None:
    """Audit finding 6, half two: keying only from the Bearer header meant the
    HttpOnly-cookie dashboard escaped the tenant/user tiers on EVERY request —
    a tenant could not be capped, and its budget was burned IP by IP."""
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    client = FakeRedis(decode_responses=True)
    app = _rate_app(client)
    token = _token(uuid.uuid4(), uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        first = await http.get(
            ORDERS_PATH, headers=_ip_headers("5.5.5.1"), cookies={"access_token": token}
        )
        second = await http.get(
            ORDERS_PATH, headers=_ip_headers("5.5.5.2"), cookies={"access_token": token}
        )

    assert first.status_code == 200
    assert second.status_code == 429, "distinct IPs, same tenant — the tier must catch it"
    assert second.json()["tier"] == "tenant"
    await client.aclose()


async def test_auth_bucket_fails_closed_when_redis_is_down() -> None:
    class ExplodingRedis:
        async def eval(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("redis down")

    app = _rate_app(ExplodingRedis())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        auth = await client.post("/api/v1/auth/login", headers=_ip_headers("1.1.1.1"))
        api = await client.get("/api/v1/orders", headers=_ip_headers("1.1.1.1"))

    assert auth.status_code == 429, "brute-force protection must survive an outage"
    assert api.status_code == 200, "throughput tiers fail open"


# ---------------------------------------------------------------------------
# DB-backed tests
# ---------------------------------------------------------------------------


async def test_idempotency_same_key_performs_effect_once(db, tenant_ctx) -> None:
    scope = idem_scope(tenant_ctx.tenant_id, "POST", ORDERS_PATH)
    digest = body_hash(ORDERS_BODY)
    effects = 0

    claim = await IdempotencyService.begin(
        db, scope=scope, key="key-1", request_hash=digest
    )
    assert claim.outcome == NEW
    if claim.outcome == NEW:
        effects += 1
    await IdempotencyService.complete(
        db,
        scope=scope,
        key="key-1",
        status_code=201,
        body=b'{"id":"order-1"}',
        content_type="application/json",
    )

    replay = await IdempotencyService.begin(
        db, scope=scope, key="key-1", request_hash=digest
    )
    assert replay.outcome == REPLAY
    if replay.outcome == NEW:
        effects += 1
    assert replay.response is not None
    assert replay.response["status"] == 201
    assert effects == 1


async def test_idempotency_same_key_different_body_conflicts(db, tenant_ctx) -> None:
    scope = idem_scope(tenant_ctx.tenant_id, "POST", ORDERS_PATH)
    await IdempotencyService.begin(
        db, scope=scope, key="key-2", request_hash=body_hash(b'{"amount": 10}')
    )

    claim = await IdempotencyService.begin(
        db, scope=scope, key="key-2", request_hash=body_hash(b'{"amount": 99}')
    )
    assert claim.outcome == CONFLICT


async def test_idempotency_scope_isolates_tenants(db, tenant_ctx) -> None:
    digest = body_hash(ORDERS_BODY)
    scope_a = idem_scope(uuid.uuid4(), "POST", ORDERS_PATH)
    scope_b = idem_scope(uuid.uuid4(), "POST", ORDERS_PATH)

    first = await IdempotencyService.begin(
        db, scope=scope_a, key="shared", request_hash=digest
    )
    # The same client-chosen key under another tenant is a new reservation.
    second = await IdempotencyService.begin(
        db, scope=scope_b, key="shared", request_hash=digest
    )
    assert first.outcome == NEW
    assert second.outcome == NEW


async def test_stale_version_fails_with_409_and_does_not_write(db, tenant_ctx) -> None:
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Acme")
    db.add(customer)
    await db.flush()
    start_version = customer.version
    assert start_version is not None

    with pytest.raises(ConflictError) as exc_info:
        await apply_versioned_update(db, customer, '"999"', {"name": "Overwritten"})
    assert exc_info.value.http_status == 409

    await db.refresh(customer)
    assert customer.name == "Acme", "a stale If-Match must not write"
    assert customer.version == start_version


async def test_current_version_update_succeeds(db, tenant_ctx) -> None:
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Acme")
    db.add(customer)
    await db.flush()
    start_version = customer.version

    await apply_versioned_update(db, customer, f'"{start_version}"', {"name": "Renamed"})

    assert customer.name == "Renamed"
    assert customer.version == start_version + 1
    await db.refresh(customer)
    assert customer.name == "Renamed"
    assert customer.version == start_version + 1


async def test_version_check_is_atomic_against_a_concurrent_writer(db, tenant_ctx) -> None:
    """The DB decides, not a Python read-then-write.

    A concurrent writer bumps the row WITHOUT going through our ORM object, so
    ``customer.version`` is stale — exactly the lost-update situation. A
    check-then-act guard using that in-memory value would pass and clobber the
    concurrent write; the atomic WHERE-clause update must not.
    """
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Acme")
    db.add(customer)
    await db.flush()
    stale_etag = f'"{customer.version}"'

    await db.execute(
        sa.update(Customer)
        .where(Customer.id == customer.id)
        .values(name="Concurrent", version=Customer.version + 1)
        .execution_options(synchronize_session=False)
    )
    # The ORM object still reports the OLD version — the stale ETag looks valid.
    assert customer.version == int(stale_etag.strip('"'))

    with pytest.raises(ConflictError):
        await apply_versioned_update(db, customer, stale_etag, {"name": "Mine"})

    winner = (
        await db.execute(sa.select(Customer.name).where(Customer.id == customer.id))
    ).scalar_one()
    assert winner == "Concurrent", "the stale writer must not win"


async def test_expired_key_is_reclaimed_on_claim(db, tenant_ctx) -> None:
    """expires_at is READ, not just written: an expired key is free again."""
    from datetime import UTC, datetime, timedelta

    from app.modules.platform.models import IdempotencyKey

    scope = idem_scope(tenant_ctx.tenant_id, "POST", ORDERS_PATH)
    digest = body_hash(ORDERS_BODY)
    db.add(
        IdempotencyKey(
            scope=scope,
            key="old",
            request_hash=digest,
            response=None,
            status="processed",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db.flush()

    claim = await IdempotencyService.begin(
        db, scope=scope, key="old", request_hash=digest
    )
    assert claim.outcome == NEW, "an expired key must not block a new attempt"


async def test_purge_expired_removes_only_expired_keys(db, tenant_ctx) -> None:
    from datetime import UTC, datetime, timedelta

    from app.modules.platform.models import IdempotencyKey

    scope = idem_scope(tenant_ctx.tenant_id, "POST", ORDERS_PATH)
    db.add_all(
        [
            IdempotencyKey(
                scope=scope,
                key="dead",
                request_hash="h",
                response=None,
                status="processed",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
            IdempotencyKey(
                scope=scope,
                key="live",
                request_hash="h",
                response=None,
                status="processed",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
        ]
    )
    await db.flush()

    removed = await IdempotencyService.purge_expired(db)
    # >= 1 rather than == 1: the sweep is table-wide, so a committed leftover
    # from another run must not make this flaky.
    assert removed >= 1
    remaining = (
        await db.execute(
            sa.select(IdempotencyKey.key).where(IdempotencyKey.scope == scope)
        )
    ).scalars().all()
    assert remaining == ["live"]


async def test_a_retried_webhook_endpoint_registration_creates_exactly_one_endpoint(
    db, tenant_ctx, monkeypatch
) -> None:
    """The 2.1 gap, closed end-to-end: the same register POST twice with the
    same Idempotency-Key must leave ONE active endpoint, not two.

    Drives the real app (the IdempotencyMiddleware is innermost on the real
    stack) with the auth context swapped and the middleware's Postgres store
    bound to THIS test's connection, so the reservation rows roll back with the
    test. The SSRF url guard is bypassed — the register route re-validates the
    target at write time and the test URL is deliberately fake.
    """
    from datetime import UTC, datetime

    from app.main import create_app
    from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
    from app.modules.platform.models import IdempotencyKey, WebhookEndpoint
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # The middleware's store opens its own session (SessionLocal read at
    # construction time, i.e. inside create_app) — bind it to the test
    # connection so the reservation commits are visible and rolled back.
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.idempotency.SessionLocal", factory)
    # The register route re-validates the target URL at write time (S6); the
    # test URL is deliberately fake, so the guard is bypassed here — it is
    # pinned by test_webhook_dispatcher.py on its own.
    monkeypatch.setattr(
        "app.modules.platform.service.assert_public_url", lambda url: None
    )

    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id,
                tenant_id=tenant_ctx.tenant_id,
                role_code=tenant_ctx.role.code,
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code=tenant_ctx.role.code,
            permission_codes={"settings:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx

    body = {"url": "https://hooks.example.test/salesos", "events": ["order.paid"]}
    headers = {"Idempotency-Key": "reg-e2e-1"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/webhook-endpoints", json=body, headers=headers
        )
        # A client that lost the first response retries the SAME request.
        second = await client.post(
            "/api/v1/webhook-endpoints", json=body, headers=headers
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"], "the replay is the FIRST endpoint"
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert second.json()["secret"] == first.json()["secret"], (
        "the retry cannot mint a second signing secret"
    )

    endpoints = (
        await db.execute(
            sa.select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_ctx.tenant_id
            )
        )
    ).scalars().all()
    assert len(endpoints) == 1, (
        "the documented 2.1 failure mode was a second ACTIVE endpoint from a "
        "retried registration"
    )

    # And the reservation is retained for the retention window, not released.
    stored = (
        await db.execute(
            sa.select(IdempotencyKey).where(IdempotencyKey.key == "reg-e2e-1")
        )
    ).scalars().all()
    assert [r.status for r in stored] == ["processed"]
    assert all(r.expires_at > datetime.now(UTC) for r in stored), (
        "expires_at must sit inside the 7-day retention window"
    )
