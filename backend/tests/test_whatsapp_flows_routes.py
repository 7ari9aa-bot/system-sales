"""The WhatsApp Flows lifecycle, from FIHRIST.

`WhatsAppFlowsClient` (create / upload_asset / publish / list) was written and tested but had no
caller anywhere: FIHRIST could send a flow message and read the `nfm_reply` that came back, but a
Flow could only be created and published in Meta's own console. These tests drive the real routes.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.conversations.routers import whatsapp_flows as wf
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from tests.security.test_role_authz_matrix import _authz_app

pytestmark = pytest.mark.asyncio

CREDS = {"access_token": "tok", "waba_id": "WABA1"}


def _graph(seen: list, *, status: int = 200, payload: dict | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.content.decode() or None))
        if payload is not None:
            return httpx.Response(status, json=payload)
        return httpx.Response(200, json={"id": "FLOW1", "success": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _request(db, ctx, method, path, *, body=None, seen=None, creds=CREDS, **graph_kw):
    app = _authz_app()
    inner = TenantContext(
        session=db,
        user=AuthedUser(
            id=ctx.user.id, tenant_id=ctx.tenant_id, role_code="x", is_platform_admin=False
        ),
        tenant_id=ctx.tenant_id,
        role_code="x",
        permission_codes={"conversations:read", "conversations:write"},
    )
    app.dependency_overrides[get_tenant_ctx] = lambda: inner

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db

    async def _creds(_ctx):
        if creds is None:
            from app.core.errors import ConflictError

            raise ConflictError("WhatsApp is not connected")
        return creds

    client = _graph(seen if seen is not None else [], **graph_kw)
    original_creds = wf._credentials
    original_http = httpx.AsyncClient

    wf._credentials = _creds

    # The gateway builds its own client when none is passed; point it at the mock transport.
    import app.modules.conversations.gateway.whatsapp_flows as flows_mod

    original_call = flows_mod.WhatsAppFlowsClient._call

    async def _call(self, method, url, token, *, what, json_body=None, _client=None):
        return await original_call(
            self, method, url, token, what=what, json_body=json_body, _client=client
        )

    flows_mod.WhatsAppFlowsClient._call = _call
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=20
        ) as api:
            return await api.request(method, path, json=body)
    finally:
        wf._credentials = original_creds
        flows_mod.WhatsAppFlowsClient._call = original_call
        httpx.AsyncClient = original_http
        await client.aclose()


async def test_a_flow_is_created_as_a_draft_and_its_id_comes_back(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db, tenant_ctx, "POST", "/api/v1/whatsapp/flows", body={"name": "order_status"}, seen=seen
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["flow_id"] == "FLOW1"
    assert resp.json()["status"] == "DRAFT"
    method, path, raw = seen[0]
    assert method == "POST" and path.endswith("/WABA1/flows")
    assert "order_status" in raw


async def test_the_flow_json_is_uploaded_to_the_flow(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/whatsapp/flows/FLOW1/assets",
        body={"flow_json": {"version": "6.0", "screens": []}},
        seen=seen,
    )
    assert resp.status_code == 200, resp.text
    method, path, raw = seen[0]
    assert method == "POST" and path.endswith("/FLOW1/assets")
    assert "FLOW_JSON" in raw


async def test_metas_own_validation_errors_are_passed_through(db, tenant_ctx):
    """The person who wrote the JSON is the only one who can fix Meta's complaint."""
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/whatsapp/flows/FLOW1/assets",
        body={"flow_json": {"version": "6.0"}},
        seen=seen,
        status=400,
        payload={"error": {"message": "INVALID_FLOW_JSON: screen SUCCESS is missing a title"}},
    )
    assert resp.status_code == 400
    assert "SUCCESS is missing a title" in resp.text


async def test_publishing_calls_metas_publish_endpoint(db, tenant_ctx):
    seen: list = []
    resp = await _request(db, tenant_ctx, "POST", "/api/v1/whatsapp/flows/FLOW1/publish", seen=seen)
    assert resp.status_code == 200, resp.text
    assert resp.json()["published"] is True
    method, path, _raw = seen[0]
    assert method == "POST" and path.endswith("/FLOW1/publish")


async def test_listing_reads_the_business_accounts_flows(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "GET",
        "/api/v1/whatsapp/flows",
        seen=seen,
        payload={"data": [{"id": "F1", "name": "order_status", "status": "PUBLISHED"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["status"] == "PUBLISHED"
    method, path, _raw = seen[0]
    assert method == "GET" and path.endswith("/WABA1/flows")


async def test_a_disconnected_channel_is_a_conflict_not_a_500(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db, tenant_ctx, "POST", "/api/v1/whatsapp/flows", body={"name": "x"}, seen=seen, creds=None
    )
    assert resp.status_code == 409
    assert seen == []


async def test_an_empty_flow_json_never_leaves_the_server(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/whatsapp/flows/FLOW1/assets",
        body={"flow_json": {}},
        seen=seen,
    )
    assert resp.status_code == 400
    assert seen == []
