"""W16: finishing the WhatsApp signup twice must not turn a success into a refusal.

The popup's authorization code works once. When the first `/complete` succeeded but its reply was
lost, the browser (or the owner, pressing connect again) sent the same request. It re-ran the code
exchange, Meta refused the spent code, and the screen said "Meta rejected the WhatsApp
authorization code" about a channel that was in fact connected.
"""

from __future__ import annotations

import httpx
import pytest

from app.platform.platform.models import Integration
from tests.test_whatsapp_connect_ordering_and_retry import _connect, _meta, _rows

pytestmark = pytest.mark.asyncio


def _spent_code_meta(seen):
    """A Meta that, like the real one, refuses an authorization code the second time."""
    used = {"n": 0}
    inner = _meta(seen, status_reply="CONNECTED")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/access_token"):
            used["n"] += 1
            if used["n"] > 1:
                seen.append((request.method, request.url.path))
                return httpx.Response(400, json={"error": {"code": 100, "message": "used"}})
        return inner(request)

    return handler


async def test_a_repeat_of_a_finished_connect_returns_the_same_success(monkeypatch, db, tenant_ctx):
    seen: list[tuple[str, str]] = []
    handler = _spent_code_meta(seen)

    first = await _connect(monkeypatch, db, tenant_ctx, handler)
    assert first.status_code == 201, first.text
    again = await _connect(monkeypatch, db, tenant_ctx, handler)

    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["phone_number_id"] == "777"
    assert again.json()["status"] == "active"
    assert len(await _rows(db, tenant_ctx)) == 1


async def test_the_repeat_never_goes_back_to_meta(monkeypatch, db, tenant_ctx):
    """No second exchange, register or subscribe: each spends a one-time code or an attempt."""
    seen: list[tuple[str, str]] = []
    handler = _spent_code_meta(seen)
    await _connect(monkeypatch, db, tenant_ctx, handler)
    seen.clear()

    await _connect(monkeypatch, db, tenant_ctx, handler)

    assert seen == [], f"the repeat called Meta: {seen}"


async def test_the_repeat_does_not_leak_a_credential(monkeypatch, db, tenant_ctx):
    seen: list[tuple[str, str]] = []
    handler = _spent_code_meta(seen)
    await _connect(monkeypatch, db, tenant_ctx, handler)

    again = await _connect(monkeypatch, db, tenant_ctx, handler)

    assert again.status_code == 201, again.text
    assert "TOKEN-123" not in again.text


async def test_a_channel_that_needs_reconnecting_really_reconnects(monkeypatch, db, tenant_ctx):
    """The shortcut is for a channel that is already working. A dead grant must be re-linked."""
    seen: list[tuple[str, str]] = []
    handler = _meta(seen, status_reply="CONNECTED")
    first = await _connect(monkeypatch, db, tenant_ctx, handler)
    assert first.status_code == 201, first.text
    (row,) = await _rows(db, tenant_ctx)
    row.status = "reauth_required"
    await db.flush()
    seen.clear()

    again = await _connect(monkeypatch, db, tenant_ctx, handler)

    assert again.status_code == 201, again.text
    assert any(p.endswith("/oauth/access_token") for _m, p in seen), "it must re-run the link"
    refreshed = (await _rows(db, tenant_ctx))[0]
    assert isinstance(refreshed, Integration) and refreshed.status == "active"
