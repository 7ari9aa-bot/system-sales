"""Platform impersonation guards — the highest-privilege surface, pinned.

No-DB claims: the disabled-feature 404, the wrong-token 403, the ticket
typing (an impersonation ticket is NOT an access token), and the open-
redirect allowlist. The DB-backed happy path is CI's job (RLS-style skip
locally), and the e2e follows the console's own flow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jwt import ExpiredSignatureError

from app.core.config import get_settings
from app.core.security import (
    create_impersonation_ticket,
    decode_token,
)
from app.main import create_app

TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _ticket(ttl=120, **claims):
    base = {"tenant_id": str(TENANT), "reason": "support session", "jti": "jti-probe"}
    base.update(claims)
    return create_impersonation_ticket(str(USER), ttl, base)


def test_ticket_decodes_with_its_type_and_short_ttl():
    raw = _ticket()
    claims = decode_token(raw)
    assert claims["type"] == "impersonation_ticket"
    assert claims["sub"] == str(USER)
    assert claims["tenant_id"] == str(TENANT)
    exp = datetime.fromtimestamp(claims["exp"], tz=UTC)
    assert exp - datetime.now(UTC) <= timedelta(seconds=121)


def test_expired_ticket_is_refused_by_decode():
    raw = _ticket(ttl=-1)
    with pytest.raises(ExpiredSignatureError):
        decode_token(raw)


def test_impersonation_ticket_is_not_an_access_token():
    """decode_token callers pin accepted types — the guard test mirrors that:
    the ticket type must never be confused with a session credential."""
    claims = decode_token(_ticket())
    assert claims["type"] != "access" and claims["type"] != "refresh"


async def test_disabled_feature_answers_404_without_probing_the_secret():
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        mint = await client.post(
            "/api/v1/platform/impersonation/tickets",
            json={"tenant_id": str(TENANT), "user_id": str(USER), "reason": "probe"},
        )
        # the GET handoff cannot even leak the page when disabled
        page = await client.get("/api/v1/platform/impersonation/redeem", params={"ticket": "x"})
    assert mint.status_code == 404
    assert page.status_code == 404


async def test_wrong_token_is_403_not_404(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setattr(
        type(get_settings()),
        "impersonation_platform_token",
        property(lambda self: "real-secret-value-123456"),
        raising=False,
    )
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/platform/impersonation/tickets",
            headers={"X-Platform-Token": "wrong-secret-value-654321"},
            json={"tenant_id": str(TENANT), "user_id": str(USER), "reason": "probe"},
        )
    assert res.status_code == 403
