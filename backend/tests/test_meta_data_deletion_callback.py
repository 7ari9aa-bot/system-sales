"""Meta's data-deletion callback: a signed request opens a deletion request, nothing more.

Meta refuses to take an app Live without a deletion callback, and the callback is reachable by
anyone. So it must (1) believe only requests signed with our app secret, (2) never erase on its
own, (3) not reveal whether a person is a customer, and (4) answer with the url and code Meta needs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy import text as sa_text

from app.core.db import bind_tenant
from app.applications.apparel.modules.customers.models import Customer, CustomerIdentity
from app.platform.identity.deps import get_db
from app.platform.identity.models import Tenant
from app.platform.privacy.meta_deletion import (
    InvalidSignedRequest,
    deletion_status,
    file_deletion_request,
    parse_signed_request,
)
from app.platform.privacy.models import DataSubjectRequest

SECRET = "test-app-secret"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def signed(payload: dict, secret: str = SECRET) -> str:
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{_b64(sig)}.{body}"


def _payload(user_id: str = "PSID-1") -> dict:
    return {"algorithm": "HMAC-SHA256", "user_id": user_id, "issued_at": 1700000000}


# ---- signature ----------------------------------------------------------------------------


def test_a_request_signed_with_our_secret_is_believed() -> None:
    assert parse_signed_request(signed(_payload("42")), SECRET)["user_id"] == "42"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "no-dot",
        ".onlypayload",
        "onlysig.",
        "!!!.???",
        signed(_payload(), secret="someone-elses-secret"),
        signed({"algorithm": "none", "user_id": "1"}),
        signed({"algorithm": "HMAC-SHA1", "user_id": "1"}),
    ],
)
def test_anything_else_is_refused(bad: str) -> None:
    with pytest.raises(InvalidSignedRequest):
        parse_signed_request(bad, SECRET)


def test_without_a_configured_secret_nothing_is_believed() -> None:
    with pytest.raises(InvalidSignedRequest):
        parse_signed_request(signed(_payload(), secret=""), "")


def test_a_tampered_payload_fails_the_signature() -> None:
    good = signed(_payload("victim"))
    sig, _, _body = good.partition(".")
    forged_body = _b64(json.dumps(_payload("someone-else")).encode())
    with pytest.raises(InvalidSignedRequest):
        parse_signed_request(f"{sig}.{forged_body}", SECRET)


# ---- filing -------------------------------------------------------------------------------


async def _customer(db, tenant_id, *, channel="messenger", external_id="PSID-1") -> uuid.UUID:
    await bind_tenant(db, tenant_id)
    customer = Customer(tenant_id=tenant_id, name="Deletion Customer")
    db.add(customer)
    await db.flush()
    db.add(
        CustomerIdentity(
            tenant_id=tenant_id, customer_id=customer.id, channel=channel, external_id=external_id
        )
    )
    await db.flush()
    return customer.id


async def _requests(db, tenant_id) -> list[DataSubjectRequest]:
    await bind_tenant(db, tenant_id)
    return list(
        (
            await db.execute(
                select(DataSubjectRequest).where(DataSubjectRequest.tenant_id == tenant_id)
            )
        ).scalars()
    )


async def test_a_known_person_gets_a_pending_delete_request(db, tenant_ctx) -> None:
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    customer_id = await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    filed = await file_deletion_request(db, ext)
    assert filed.filed is True
    [request] = await _requests(db, tenant_ctx.tenant_id)
    assert (request.customer_id, request.request_type, request.status) == (
        customer_id,
        "delete",
        "pending",
    )
    assert request.id.hex == filed.confirmation_code


async def test_filing_never_erases_the_customer(db, tenant_ctx) -> None:
    """The signature is the only gate on the open internet, so it must not trigger erasure."""
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    customer_id = await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    await file_deletion_request(db, ext)
    await bind_tenant(db, tenant_ctx.tenant_id)
    customer = (await db.execute(select(Customer).where(Customer.id == customer_id))).scalar_one()
    assert customer.name == "Deletion Customer"


async def test_an_unknown_person_files_nothing_but_still_gets_a_code(db, tenant_ctx) -> None:
    """Otherwise the callback would tell a stranger who is and is not a customer."""
    filed = await file_deletion_request(db, f"nobody-{uuid.uuid4().hex}")
    assert filed.filed is False and len(filed.confirmation_code) == 32
    assert await _requests(db, tenant_ctx.tenant_id) == []


async def test_an_id_claimed_by_two_customers_files_nothing(db, tenant_ctx) -> None:
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    await _customer(db, other.id, external_id=ext)
    filed = await file_deletion_request(db, ext)
    assert filed.filed is False
    assert await _requests(db, tenant_ctx.tenant_id) == []


async def test_a_non_meta_channel_with_the_same_id_is_not_matched(db, tenant_ctx) -> None:
    ext = f"id-{uuid.uuid4().hex[:10]}"
    await _customer(db, tenant_ctx.tenant_id, channel="telegram", external_id=ext)
    assert (await file_deletion_request(db, ext)).filed is False


# ---- status -------------------------------------------------------------------------------


async def test_status_reports_pending_then_completed(db, tenant_ctx) -> None:
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    filed = await file_deletion_request(db, ext)
    assert await deletion_status(db, filed.confirmation_code) == "pending"
    await db.execute(
        sa_text("UPDATE data_subject_requests SET status='completed' WHERE id = :i"),
        {"i": uuid.UUID(filed.confirmation_code)},
    )
    assert await deletion_status(db, filed.confirmation_code) == "completed"


@pytest.mark.parametrize("code", ["", "garbage", str(uuid.uuid4()), uuid.uuid4().hex])
async def test_an_unknown_code_reveals_nothing(db, code: str) -> None:
    assert await deletion_status(db, code) == "unknown"


async def test_status_only_answers_for_requests_the_callback_opened(db, tenant_ctx) -> None:
    """An ordinary merchant-opened request must not be readable through the public URL."""
    customer_id = await _customer(db, tenant_ctx.tenant_id, external_id="x-1")
    request = DataSubjectRequest(
        tenant_id=tenant_ctx.tenant_id, customer_id=customer_id, request_type="delete"
    )
    db.add(request)
    await db.flush()
    assert await deletion_status(db, request.id.hex) == "unknown"


# ---- HTTP ---------------------------------------------------------------------------------


def _client(db: Any, monkeypatch, *, secret: str = SECRET) -> AsyncClient:
    """The REAL app (so routing, prefixes and error handlers are the production ones)."""
    from app.core import config
    from app.core.idempotency import IdempotencyMiddleware
    from app.core.middleware import RateLimitMiddleware
    from app.main import create_app

    settings = config.get_settings()
    monkeypatch.setattr(settings, "meta_app_secret", secret, raising=False)
    monkeypatch.setattr(settings, "messenger_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "instagram_app_secret", "", raising=False)
    monkeypatch.setattr(settings, "api_public_base_url", "https://api.example.test", raising=False)
    app = create_app()
    # The two middlewares that open their own Redis/Postgres connection are not what is tested.
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None

    async def _session() -> Any:
        yield db

    app.dependency_overrides[get_db] = _session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20)


async def test_the_callback_answers_with_the_url_and_code_meta_needs(
    db, tenant_ctx, monkeypatch
) -> None:
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    async with _client(db, monkeypatch) as client:
        resp = await client.post(
            "/api/v1/webhooks/meta/data-deletion",
            content=f"signed_request={signed(_payload(ext))}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["url"] == (
            f"https://api.example.test/api/v1/webhooks/meta/data-deletion/status/"
            f"{body['confirmation_code']}"
        )
        status = await client.get(
            f"/api/v1/webhooks/meta/data-deletion/status/{body['confirmation_code']}"
        )
        assert status.json()["status"] == "pending"


async def test_a_forged_callback_is_refused_and_files_nothing(db, tenant_ctx, monkeypatch) -> None:
    ext = f"psid-{uuid.uuid4().hex[:10]}"
    await _customer(db, tenant_ctx.tenant_id, external_id=ext)
    async with _client(db, monkeypatch) as client:
        resp = await client.post(
            "/api/v1/webhooks/meta/data-deletion",
            content=f"signed_request={signed(_payload(ext), secret='attacker')}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert resp.status_code == 400
    assert await _requests(db, tenant_ctx.tenant_id) == []


async def test_a_missing_body_is_a_400_not_a_500(db, monkeypatch) -> None:
    async with _client(db, monkeypatch) as client:
        resp = await client.post("/api/v1/webhooks/meta/data-deletion", content=b"")
    assert resp.status_code == 400


async def test_the_status_route_is_not_swallowed_by_the_channel_route(db, monkeypatch) -> None:
    async with _client(db, monkeypatch) as client:
        resp = await client.get("/api/v1/webhooks/meta/data-deletion/status/nope")
    assert resp.status_code == 404
    assert "confirmation" in resp.text.lower()
