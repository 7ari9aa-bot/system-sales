"""A connect that fails for a reason the operator cannot see is a connect nobody can fix.

The callback answered `invalid_state` and choose-page answered "This choice expired" without a
diagnostic, so a customer who could not link a channel left no trace: the operator could not tell
an expired window from a tampered state from a corrupt ticket.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from app.core import meta_diagnostics
from app.core.errors import ValidationError
from app.core.security import create_access_token, create_oauth_state_token
from app.modules.customers import meta_oauth as mo
from tests.test_meta_oauth import _app, _config_patch, _popup_result

pytestmark = pytest.mark.asyncio

CALLBACK = "/api/v1/integrations/meta/oauth/callback"


@pytest.fixture
def flags(monkeypatch):
    """Every diagnostic the link flow raises, as (key, provider, details)."""
    seen: list[tuple[str, str | None, dict]] = []

    async def record(key, provider, tenant_id, details=None):
        seen.append((key, provider, details or {}))

    monkeypatch.setattr(mo, "_flag", record)
    return seen


async def _callback(db, tenant_ctx, **params):
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        return await client.get(CALLBACK, params=params, follow_redirects=False)


def test_the_new_diagnostic_keys_are_catalogued():
    for key in ("link.state_invalid", "link.choice_ticket_invalid"):
        assert key in meta_diagnostics.CATALOG, f"{key} must be explained to the operator"


async def test_a_garbled_state_is_recorded(db, tenant_ctx, monkeypatch, flags):
    _config_patch(monkeypatch)
    response = await _callback(db, tenant_ctx, code="c", state="not-a-jwt")
    assert _popup_result(response)["error"] == "invalid_state"
    assert [(f[0], f[2]["reason"]) for f in flags] == [("link.state_invalid", "undecodable")]


async def test_a_state_that_is_not_an_oauth_state_is_recorded(db, tenant_ctx, monkeypatch, flags):
    _config_patch(monkeypatch)
    response = await _callback(
        db, tenant_ctx, code="c", state=create_access_token(str(tenant_ctx.user.id))
    )
    assert _popup_result(response)["error"] == "invalid_state"
    assert [(f[0], f[2]["reason"]) for f in flags] == [("link.state_invalid", "wrong_type")]


async def test_an_unknown_provider_in_the_state_is_recorded(db, tenant_ctx, monkeypatch, flags):
    _config_patch(monkeypatch)
    state = create_oauth_state_token(
        str(tenant_ctx.user.id), {"tenant_id": str(tenant_ctx.tenant_id), "provider": "tiktok"}
    )
    response = await _callback(db, tenant_ctx, code="c", state=state)
    assert _popup_result(response)["error"] == "invalid_provider"
    assert [(f[0], f[2]["reason"]) for f in flags] == [("link.state_invalid", "unknown_provider")]


async def test_a_callback_without_code_is_recorded(db, tenant_ctx, monkeypatch, flags):
    _config_patch(monkeypatch)
    response = await _callback(db, tenant_ctx, state="x")
    assert _popup_result(response)["error"] == "missing_code_or_state"
    assert [(f[0], f[2]["reason"]) for f in flags] == [
        ("link.state_invalid", "missing_code_or_state")
    ]


async def test_no_diagnostic_carries_the_state_or_the_code(db, tenant_ctx, monkeypatch, flags):
    """The state is a signed credential and the code is single-use: neither goes in a trail."""
    _config_patch(monkeypatch)
    state = "eyJhbGciOiJIUzI1NiJ9.secret-looking-body.signature"
    await _callback(db, tenant_ctx, code="the-authorization-code", state=state)
    blob = json.dumps(flags)
    assert state not in blob and "the-authorization-code" not in blob


# ---- the page-choice ticket ---------------------------------------------------------------


@pytest.fixture
def redis(monkeypatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(mo, "get_redis", lambda: client)
    return client


class _Ctx:
    def __init__(self):
        self.tenant_id = uuid.uuid4()
        self.user = type("U", (), {"id": str(uuid.uuid4())})()


async def _choose(ticket):
    body = mo.MetaOAuthPageChoiceIn(ticket=ticket, page_id="111")
    return await mo.meta_oauth_choose_page(body, session=None, ctx=_Ctx())


async def test_an_unknown_or_expired_ticket_is_recorded(redis, flags):
    with pytest.raises(ValidationError, match="expired"):
        await _choose("x" * 24)
    assert [(f[0], f[2]["reason"]) for f in flags] == [
        ("link.choice_ticket_invalid", "missing_or_expired")
    ]


async def test_a_corrupt_ticket_is_told_apart_from_an_expired_one(redis, flags):
    """Both read 'This choice expired', so a broken ticket looked like a slow owner."""
    await redis.set(mo._page_choice_key("c" * 24), "{not json", ex=60)
    with pytest.raises(ValidationError, match="expired"):
        await _choose("c" * 24)
    assert [(f[0], f[2]["reason"]) for f in flags] == [("link.choice_ticket_invalid", "unreadable")]


async def test_the_ticket_value_is_never_written_to_a_diagnostic(redis, flags):
    ticket = "t" * 24
    with pytest.raises(ValidationError):
        await _choose(ticket)
    assert ticket not in json.dumps(flags)
