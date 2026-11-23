"""M6: the operator hears about a 500 or a dead-lettered webhook, without ever being flooded,
leaking a secret, or slowing the request that failed."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.core import ops_alerts
from app.modules.conversations.gateway.ingest import IngestService

URL = "https://hooks.example.com/services/T000/B000/XXXX"


def _settings(url=URL, cooldown=900, per_hour=20, env="production"):
    return SimpleNamespace(
        ops_alert_webhook_url=url,
        ops_alert_cooldown_seconds=cooldown,
        ops_alert_max_per_hour=per_hour,
        environment=env,
        worker_max_attempts=3,
    )


class _Redis:
    """Just enough of Redis for SET NX, INCR and EXPIRE."""

    def __init__(self):
        self.kv, self.counts = {}, {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, *_a):
        return True


class _Http:
    """Records posts; stands in for httpx.AsyncClient."""

    posts: list = []
    status = 200

    def __init__(self, *a, **kw):
        self.kwargs = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None):
        _Http.posts.append((url, json, self.kwargs))
        return SimpleNamespace(status_code=_Http.status)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    ops_alerts._reset_for_tests()
    _Http.posts, _Http.status = [], 200
    monkeypatch.setattr(ops_alerts, "get_settings", lambda: _settings())
    monkeypatch.setattr(ops_alerts, "_client_class", lambda: _Http)
    monkeypatch.setattr("app.core.net_guard.assert_public_url", lambda u: u)
    redis = _Redis()
    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    return redis


# ------------------------------------------------------------------ off by default


async def test_unset_url_sends_nothing(monkeypatch):
    monkeypatch.setattr(ops_alerts, "get_settings", lambda: _settings(url=""))
    assert ops_alerts.alerts_enabled() is False
    assert await ops_alerts.send_alert("boom", "GET /x") is False
    assert _Http.posts == []


# ------------------------------------------------------------------ delivery


async def test_an_alert_posts_text_and_content_without_following_redirects():
    assert await ops_alerts.send_alert("unhandled 500", "GET /orders", "KeyError", "rid-1") is True
    [(url, body, kwargs)] = _Http.posts
    assert url == URL
    assert body["text"] == body["content"]
    assert "unhandled 500" in body["text"] and "GET /orders" in body["text"]
    assert "request_id: rid-1" in body["text"]
    assert kwargs["follow_redirects"] is False and kwargs["timeout"] <= 5


async def test_a_rejecting_endpoint_is_reported_false_and_never_raises():
    _Http.status = 500
    assert await ops_alerts.send_alert("boom", "w") is False


async def test_a_network_error_never_raises(monkeypatch):
    class _Boom(_Http):
        async def post(self, *a, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(ops_alerts, "_client_class", lambda: _Boom)
    assert await ops_alerts.send_alert("boom", "w") is False


async def test_a_private_url_is_refused_before_anything_is_sent(monkeypatch):
    from app.core.errors import ValidationError

    def refuse(_u):
        raise ValidationError("private")

    monkeypatch.setattr("app.core.net_guard.assert_public_url", refuse)
    assert await ops_alerts.send_alert("boom", "w") is False
    assert _Http.posts == []


# ------------------------------------------------------------------ flood control


async def test_the_same_failure_is_sent_once_per_cooldown():
    assert await ops_alerts.send_alert("unhandled 500", "GET /a") is True
    assert await ops_alerts.send_alert("unhandled 500", "GET /a") is False
    assert await ops_alerts.send_alert("unhandled 500", "GET /b") is True
    assert len(_Http.posts) == 2


async def test_the_hourly_cap_bounds_the_total(monkeypatch):
    monkeypatch.setattr(ops_alerts, "get_settings", lambda: _settings(per_hour=3))
    sent = [await ops_alerts.send_alert("k", f"route-{i}") for i in range(8)]
    assert sent.count(True) == 3


async def test_with_redis_down_the_local_fallback_still_dedups_and_caps(monkeypatch):
    def down():
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis", down)
    monkeypatch.setattr(ops_alerts, "get_settings", lambda: _settings(per_hour=2))
    assert await ops_alerts.send_alert("k", "a") is True
    assert await ops_alerts.send_alert("k", "a") is False
    assert await ops_alerts.send_alert("k", "b") is True
    assert await ops_alerts.send_alert("k", "c") is False


# ------------------------------------------------------------------ no leaks


async def test_secrets_and_control_characters_never_reach_the_message():
    token = "EAAUtSPZCPZCF0BTfakefakefakefake1234567890"
    await ops_alerts.send_alert("k\nINJECT", "GET /x", f"failed access_token={token}", "rid")
    text = _Http.posts[0][1]["text"]
    assert token not in text and "access_token=" + token not in text
    assert "k\nINJECT" not in text


async def test_the_webhook_url_is_never_in_the_message():
    await ops_alerts.send_alert("k", "w", "d")
    assert URL not in _Http.posts[0][1]["text"]


async def test_the_message_is_clipped():
    await ops_alerts.send_alert("k", "w" * 5000, "d" * 5000)
    assert len(_Http.posts[0][1]["text"]) <= 1500


# ------------------------------------------------------------------ background send


async def test_fire_and_forget_does_not_wait_for_the_send(monkeypatch):
    gate = asyncio.Event()

    class _Slow(_Http):
        async def post(self, url, json=None):
            await gate.wait()
            return await super().post(url, json)

    monkeypatch.setattr(ops_alerts, "_client_class", lambda: _Slow)
    ops_alerts.fire_and_forget("k", "w")  # returns at once even though the send is blocked
    assert _Http.posts == []
    gate.set()
    await asyncio.gather(*list(ops_alerts._pending))
    assert len(_Http.posts) == 1


def test_fire_and_forget_with_no_running_loop_is_silent():
    ops_alerts.fire_and_forget("k", "w")


async def test_fire_and_forget_is_a_no_op_when_off(monkeypatch):
    monkeypatch.setattr(ops_alerts, "get_settings", lambda: _settings(url=""))
    ops_alerts.fire_and_forget("k", "w")
    assert not ops_alerts._pending


# ------------------------------------------------------------------ the two hooks


class _Result:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar


class _Session:
    def __init__(self, status):
        self.row = SimpleNamespace(
            provider="whatsapp", tenant_id=uuid.uuid4(), processing_status=status
        )
        self.calls = 0

    async def execute(self, _s):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(rowcount=1)
        if self.calls == 2:
            return _Result(first=self.row)
        return _Result(scalar=None)


async def _quarantine(status, monkeypatch):
    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr("app.core.meta_diagnostics.record_channel_issue", noop)
    monkeypatch.setattr("app.core.config.get_settings", lambda: _settings())
    await IngestService.mark_webhook_event_failed(_Session(status), uuid.uuid4(), RuntimeError("x"))
    await asyncio.gather(*list(ops_alerts._pending))


async def test_a_dead_lettered_webhook_alerts_the_operator(monkeypatch):
    await _quarantine("dead", monkeypatch)
    [(_u, body, _k)] = _Http.posts
    assert "webhook dead-lettered" in body["text"] and "whatsapp" in body["text"]
    assert "RuntimeError" in body["text"]


async def test_a_failure_with_retries_left_stays_quiet(monkeypatch):
    await _quarantine("failed", monkeypatch)
    assert _Http.posts == []


@pytest.fixture
def _restore_logging():
    """The 500 handler logs through structlog, which caches its first configuration for the whole
    process. Put structlog and the root handlers back so the tests that run after this one see the
    logging they were written for."""
    import logging

    import structlog

    handlers = logging.getLogger().handlers[:]
    formatters = [h.formatter for h in handlers]
    config = structlog.get_config().copy()
    try:
        yield
    finally:
        structlog.reset_defaults()
        structlog.configure(**config)
        for handler, formatter in zip(handlers, formatters, strict=True):
            handler.setFormatter(formatter)


async def test_the_500_handler_alerts_with_the_route_template_not_the_url(
    monkeypatch, _restore_logging
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.main import _exception_handlers

    app = FastAPI()
    _exception_handlers(app)

    @app.get("/orders/{order_id}")
    async def boom(order_id: str):
        raise KeyError("secret-row-value")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as client:
        response = await client.get("/orders/ORDER-123")
    await asyncio.gather(*list(ops_alerts._pending))
    assert response.status_code == 500
    [(_u, body, _k)] = _Http.posts
    assert "GET /orders/{order_id}" in body["text"]
    assert "ORDER-123" not in body["text"] and "secret-row-value" not in body["text"]
    assert "KeyError" in body["text"]
