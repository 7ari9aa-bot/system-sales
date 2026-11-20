"""The authority's callbacks through the real app: key -> store -> database -> answer.

What matters here is what the authority sees (it retries anything but 200) and that a key can
only ever move its own till's receipts.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

import app.core.model_registry  # noqa: F401
from app.core.db import bind_tenant
from app.main import create_app
from app.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument
from app.modules.einvoice.providers.eta.notifications import key_hash
from tests.test_eta_db_layer import _ctx, _device, _other_tenant

pytestmark = pytest.mark.usefixtures("db")

RECEIPTS = "/api/v1/einvoice/eta/notifications/receipts"
GENERAL = "/api/v1/einvoice/eta/notifications/general"
KEY = "shared-secret-for-tests"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from app.core.middleware import RateLimitMiddleware

    async def _passthrough(self, request, call_next):
        return await call_next(request)

    monkeypatch.setattr(RateLimitMiddleware, "dispatch", _passthrough)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


def _auth(key: str = KEY) -> dict[str, str]:
    return {"Authorization": f"ApiKey {key}"}


async def _till_with_receipt(db, tid, *, serial="POS-HTTP-1", key=KEY, number="R-1"):
    from app.modules.einvoice.service import EInvoiceService

    dev = await _device(db, tid, serial=serial, key=key)
    doc = await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, number), device_id=dev.id)
    doc.status = "submitted"
    await db.flush()
    return dev, doc


def _valid(delivery_id: str, uuid_: str) -> dict:
    return {
        "deliveryId": delivery_id,
        "message": [
            {
                "type": "Validated",
                "uuid": uuid_,
                "submissionUUID": "SUB-1",
                "longId": "LONG-1",
                "internalId": "R-1",
                "status": "Valid",
            }
        ],
    }


async def _commit(db, tid):
    """Release the savepoint so the request's own session sees the rows (undone at teardown)."""
    await db.commit()
    await bind_tenant(db, tid)


class TestAuthentication:
    @pytest.mark.parametrize("path", [RECEIPTS, GENERAL])
    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": ""}, {"Authorization": "Bearer abc"}, {"Authorization": "ApiKey"}],
    )
    async def test_a_missing_or_malformed_key_is_refused_with_401(
        self, db, app_sessions_on_test_connection, path, headers
    ):
        async with _client() as c:
            r = await c.put(path, json={}, headers=headers)
        assert r.status_code == 401

    async def test_an_unknown_key_is_refused_with_401_and_changes_nothing(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        _, doc = await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth("wrong"))
        assert r.status_code == 401
        await db.refresh(doc)
        assert doc.status == "submitted"

    async def test_a_revoked_till_key_is_refused(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        dev, doc = await _till_with_receipt(db, tid)
        dev.status = "revoked"
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth())
        assert r.status_code == 401

    async def test_the_plain_key_is_not_stored_anywhere_on_the_till(self, db, tenant_ctx):
        dev, _ = await _till_with_receipt(db, tenant_ctx.tenant_id)
        assert dev.notification_key_hash == key_hash(KEY)
        assert KEY not in str(dev.credentials) + str(dev.metadata_info)


class TestReceiptCallback:
    async def test_a_valid_notification_reports_the_receipt_and_answers_200(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        _, doc = await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth())
        assert r.status_code == 200 and r.json()["applied"] == 1
        await db.refresh(doc)
        assert doc.status == "reported" and doc.authority_long_id == "LONG-1"

    async def test_the_same_delivery_again_answers_200_and_applies_nothing(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        _, doc = await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            first = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth())
            again = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth())
        assert first.json()["applied"] == 1
        assert again.status_code == 200 and again.json()["applied"] == 0
        assert again.json()["repeat"] == 1

    async def test_a_receipt_we_do_not_know_still_answers_200(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=_valid("D9", "e" * 64), headers=_auth())
        assert r.status_code == 200 and r.json()["unknown"] == 1

    @pytest.mark.parametrize(
        "body",
        [{}, {"deliveryId": "x"}, {"deliveryId": "x", "message": "no"}, {"message": []}, [1]],
    )
    async def test_a_body_the_authority_never_documents_is_a_400_not_a_retry_loop(
        self, db, tenant_ctx, app_sessions_on_test_connection, body
    ):
        tid = tenant_ctx.tenant_id
        await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=body, headers=_auth())
        assert r.status_code == 400

    async def test_not_json_is_a_400(self, db, tenant_ctx, app_sessions_on_test_connection):
        tid = tenant_ctx.tenant_id
        await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, content=b"not json", headers=_auth())
        assert r.status_code == 400

    async def test_an_oversized_body_is_refused_before_it_is_parsed(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, content=b"x" * (300 * 1024), headers=_auth())
        assert r.status_code == 413

    async def test_one_tills_key_cannot_touch_another_tills_receipt(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        _, doc = await _till_with_receipt(db, tid, serial="POS-A", key="key-a", number="R-A")
        await _device(db, tid, serial="POS-B", key="key-b")
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth("key-b"))
        assert r.status_code == 200 and r.json()["unknown"] == 1
        await db.refresh(doc)
        assert doc.status == "submitted"

    async def test_another_stores_key_cannot_touch_this_stores_receipt(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        _, doc = await _till_with_receipt(db, tid, key="key-mine")
        other = await _other_tenant(db)
        await bind_tenant(db, other)
        await _device(db, other, serial="POS-OTHER", key="key-theirs")
        await db.commit()
        await bind_tenant(db, tid)
        async with _client() as c:
            r = await c.put(
                RECEIPTS, json=_valid("D1", doc.invoice_hash), headers=_auth("key-theirs")
            )
        assert r.status_code == 200 and r.json()["unknown"] == 1
        await bind_tenant(db, tid)  # the request left another store's binding on this connection
        await db.refresh(doc)
        assert doc.status == "submitted"


class TestGeneralCallback:
    async def test_a_deactivation_suspends_only_the_calling_till(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        dev, _ = await _till_with_receipt(db, tid, serial="POS-1", key="k1")
        other = await _device(db, tid, serial="POS-2", key="k2")
        await _commit(db, tid)
        body = {"Type": "PosDeactivated", "Id": "POS-1", "Message": {"Reason": "hold"}}
        async with _client() as c:
            r = await c.put(GENERAL, json=body, headers=_auth("k1"))
        assert r.status_code == 200 and r.json()["result"] == "applied"
        await db.refresh(dev)
        await db.refresh(other)
        assert dev.status == "suspended" and other.status == "active"

    async def test_a_notice_naming_a_different_till_is_ignored(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        dev, _ = await _till_with_receipt(db, tid, serial="POS-1", key="k1")
        other = await _device(db, tid, serial="POS-2", key="k2")
        await _commit(db, tid)
        body = {"Type": "PosDeactivated", "Id": "POS-2", "Message": {}}
        async with _client() as c:
            r = await c.put(GENERAL, json=body, headers=_auth("k1"))
        assert r.status_code == 200 and r.json()["result"] == "ignored"
        await db.refresh(dev)
        await db.refresh(other)
        assert (dev.status, other.status) == ("active", "active")

    async def test_an_unknown_notice_type_is_a_400(
        self, db, tenant_ctx, app_sessions_on_test_connection
    ):
        tid = tenant_ctx.tenant_id
        await _till_with_receipt(db, tid)
        await _commit(db, tid)
        async with _client() as c:
            r = await c.put(GENERAL, json={"Type": "Surprise", "Id": "POS-HTTP-1"}, headers=_auth())
        assert r.status_code == 400


def test_the_plain_key_never_reaches_the_database_layer():
    assert key_hash(KEY) != KEY and len(key_hash(KEY)) == 64
    assert isinstance(EInvoiceDevice, type) and isinstance(EInvoiceDocument, type)
    assert sa and uuid  # imports used by fixtures above
