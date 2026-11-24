"""WhatsApp Embedded Signup: a failed connect leaves nothing behind and a retry is safe.

Review items W5, W6, W8, W9. Meta is faked at the HTTP layer; the real ``/complete`` route runs
against the real database.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.secrets import decrypt_credentials_dict
from app.modules.customers import meta_whatsapp_signup as signup
from app.modules.platform.models import Integration
from tests._pos_helpers import ctx_for
from tests.test_pos_return_audit_and_day_holder import _app

pytestmark = pytest.mark.asyncio

_COMPLETE = "/api/v1/integrations/whatsapp/embedded-signup/complete"
_BODY = {"code": "AQD" + "x" * 30, "waba_id": "900", "phone_number_id": "777"}


def _meta(
    seen: list[tuple[str, str]],
    *,
    status_reply,
    register_reply=None,
    on_biz_app=True,
    number_reply=None,
):
    """``status_reply``: a status string, or a callable(request) -> httpx.Response."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "TOKEN-123"})
        if path.endswith("/phone_numbers"):
            return httpx.Response(200, json={"data": [{"id": "777"}]})
        if path.endswith("/subscribed_apps"):
            if request.method == "DELETE":
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json={"success": True})
        if path.endswith("/register"):
            if register_reply is not None:
                return register_reply(request)
            return httpx.Response(200, json={"success": True})
        if request.method == "GET" and "status" in request.url.params.get("fields", ""):
            if callable(status_reply):
                return status_reply(request)
            return httpx.Response(200, json={"status": status_reply})
        # The catch-all is Meta's answer about the number itself: its name, AND the two fields
        # the connect requires before it records the coexistence mode.
        if number_reply is not None:
            return number_reply(request)
        return httpx.Response(
            200,
            json={
                "id": "777",
                "display_phone_number": "+20 100",
                "verified_name": "Fihrist Shop",
                "is_on_biz_app": on_biz_app,
                "platform_type": "CLOUD_API",
            },
        )

    return handler


_REAL_CLIENT = httpx.AsyncClient  # captured once: a second patch must not wrap the first fake


async def _connect(monkeypatch, db, tenant_ctx, handler):
    monkeypatch.setattr(
        signup.httpx,
        "AsyncClient",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(signup, "_whatsapp_config", lambda: ("app", "secret", "cfg"))
    owner = await ctx_for(db, tenant_ctx, "owner")
    async with AsyncClient(transport=ASGITransport(app=_app(owner)), base_url="http://t") as c:
        return await c.post(_COMPLETE, json=_BODY)


async def _rows(db, tenant_ctx):
    return (
        (
            await db.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_ctx.tenant_id,
                    Integration.provider == "whatsapp",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_a_coexistence_number_never_spends_a_register_call(monkeypatch, db, tenant_ctx):
    """W8, restated for coexistence: the number is already registered inside the Business app, so
    the connect must not burn one of Meta's ten attempts — and it must still subscribe the WABA,
    otherwise nothing is ever delivered."""
    seen: list[tuple[str, str]] = []
    r = await _connect(monkeypatch, db, tenant_ctx, _meta(seen, status_reply="PENDING"))
    assert r.status_code == 201, r.text
    paths = [p for _m, p in seen]
    assert not any(p.endswith("/register") for p in paths)
    assert f"/{signup._GRAPH_VERSION}/900/subscribed_apps" in paths


async def test_a_refused_number_never_subscribes_the_waba(monkeypatch, db, tenant_ctx):
    """A number Meta says is not on the Business app is refused before any subscription is made."""
    seen: list[tuple[str, str]] = []
    handler = _meta(seen, status_reply="PENDING", on_biz_app=False)
    r = await _connect(monkeypatch, db, tenant_ctx, handler)
    assert r.status_code >= 400
    assert not any(p.endswith("/subscribed_apps") for _m, p in seen)
    assert await _rows(db, tenant_ctx) == []


async def test_an_unreadable_number_read_is_refused_not_treated_as_coexistence(
    monkeypatch, db, tenant_ctx
):
    """W5: when Meta cannot say whether the number is on the Business app, the connect must fail —
    guessing "yes" would connect a number that cannot receive."""
    seen: list[tuple[str, str]] = []

    def broken(_request):
        return httpx.Response(500, text="<html>oops</html>")

    r = await _connect(
        monkeypatch, db, tenant_ctx, _meta(seen, status_reply="PENDING", number_reply=broken)
    )
    assert r.status_code >= 400, "an unreadable number read is a retryable failure, not a pass"
    assert not any(p.endswith("/register") for _m, p in seen)
    assert await _rows(db, tenant_ctx) == []


async def test_a_retry_after_a_lost_response_leaves_one_connection(monkeypatch, db, tenant_ctx):
    """W6, restated for coexistence: nothing is registered, so the retry risk is a SECOND row.

    The first attempt dies after the credentials are stored; the retry must end with exactly one
    integration and a token that still decrypts.
    """
    seen: list[tuple[str, str]] = []

    def lost(_request):
        raise httpx.ReadTimeout("response lost", request=_request)

    first = await _connect(
        monkeypatch, db, tenant_ctx, _meta(seen, status_reply="PENDING", register_reply=lost)
    )
    assert first.status_code == 201, first.text

    seen2: list[tuple[str, str]] = []
    second = await _connect(monkeypatch, db, tenant_ctx, _meta(seen2, status_reply="PENDING"))
    assert second.status_code == 201, second.text

    rows = await _rows(db, tenant_ctx)
    assert len(rows) == 1
    creds = decrypt_credentials_dict(rows[0].credentials)
    assert creds["access_token"] == "TOKEN-123"
    assert "registration_pin" not in creds


async def test_a_number_already_connected_to_another_workspace_is_a_conflict_not_a_500(
    monkeypatch, db, tenant_ctx
):
    """W9: the unique index on provider identity must surface as a clean 409."""
    from sqlalchemy.exc import IntegrityError

    seen: list[tuple[str, str]] = []
    real_flush = db.flush

    async def boom(*a, **k):
        if any(isinstance(o, Integration) for o in db.new):
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        return await real_flush(*a, **k)

    monkeypatch.setattr(db, "flush", boom)
    r = await _connect(monkeypatch, db, tenant_ctx, _meta(seen, status_reply="CONNECTED"))
    assert r.status_code == 409, r.text
