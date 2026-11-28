"""The import routes, through the real app: permissions, upload limits, the flow, the report."""

from __future__ import annotations

import io

import pytest
import sqlalchemy as sa
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.middleware import MAX_IMPORT_UPLOAD_BYTES
from app.main import create_app
from app.platform.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.applications.apparel.modules.inventory.models import Warehouse

BOTH = {"products:write", "inventory:write"}


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FILE = _xlsx(
    {
        "Products": [["Product ref", "Name"], ["tee", "قميص"], ["bad", ""]],
        "Variants": [["Product ref", "SKU", "Price"], ["tee", "TEE-1", "99.50"]],
    }
)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
async def api(db, tenant_ctx):
    """A client whose requests run the real routes inside the test's rolled-back transaction."""

    def build(permissions: set[str]) -> AsyncClient:
        app = create_app()
        user = AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            is_platform_admin=False,
        )
        ctx = TenantContext(
            session=db,
            user=user,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=permissions,
        )

        async def _session():
            yield db

        app.dependency_overrides[get_tenant_ctx] = lambda: ctx
        app.dependency_overrides[get_db] = Depends(_session)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20)

    return build


async def _upload(client, data=FILE, name="catalog.xlsx"):
    return await client.post(
        "/api/v1/imports/sessions",
        params={"filename": name},
        content=data,
        headers={"content-type": XLSX},
    )


@pytest.mark.parametrize("granted", [set(), {"products:write"}, {"inventory:write"}])
async def test_every_route_needs_both_permissions(api, granted):
    """Importing writes products and the stock ledger, so one of the two is not enough."""
    some_id = "00000000-0000-0000-0000-000000000001"
    calls = [
        ("GET", "/api/v1/imports/template.xlsx"),
        ("POST", "/api/v1/imports/sessions?filename=a.xlsx"),
        ("GET", "/api/v1/imports/sessions"),
        ("GET", f"/api/v1/imports/sessions/{some_id}"),
        ("PUT", f"/api/v1/imports/sessions/{some_id}/mapping"),
        ("POST", f"/api/v1/imports/sessions/{some_id}/validate"),
        ("GET", f"/api/v1/imports/sessions/{some_id}/preview"),
        ("POST", f"/api/v1/imports/sessions/{some_id}/start"),
        ("POST", f"/api/v1/imports/sessions/{some_id}/cancel"),
        ("GET", f"/api/v1/imports/sessions/{some_id}/errors.csv"),
    ]
    async with api(granted) as client:
        for method, path in calls:
            kwargs = {"json": {}} if method == "PUT" else {}
            response = await client.request(method, path, **kwargs)
            assert response.status_code == 403, (method, path, response.status_code)


async def test_upload_returns_the_session_and_a_guess_at_the_columns(api):
    async with api(BOTH) as client:
        response = await _upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "analyzed" and body["file_name"] == "catalog.xlsx"
    assert body["sheets"]["Variants"]["mapping"]["Price"] == "price"
    assert body["sheets"]["Products"]["missing_required"] == []
    assert body["options"] == {"duplicate_policy": "create_only", "blank_policy": "keep"}


async def test_the_whole_flow_over_http_ends_with_a_queued_job(api, db, tenant_ctx):
    db.add(Warehouse(tenant_id=tenant_ctx.tenant_id, name="Main", code="MAIN"))
    async with api(BOTH) as client:
        session_id = (await _upload(client)).json()["id"]
        base = f"/api/v1/imports/sessions/{session_id}"

        assert (await client.post(f"{base}/start")).status_code == 409  # not checked yet
        checked = await client.post(f"{base}/validate")
        assert checked.status_code == 200 and checked.json()["status"] == "validated"

        preview = (await client.get(f"{base}/preview")).json()
        assert preview["stats"]["sheets"]["Products"] == {
            **preview["stats"]["sheets"]["Products"],
            "valid": 1,
            "invalid": 1,
        }
        assert preview["sample_errors"][0]["sheet"] == "Products"
        assert preview["sample_errors"][0]["row"] == 3

        started = await client.post(f"{base}/start")
        assert started.status_code == 202
        assert started.json()["status"] == "running" and started.json()["job_id"]
        assert (await client.post(f"{base}/start")).status_code == 409  # not twice

    job = (
        await db.execute(
            sa.text("select kind, correlation_id from jobs where id = :j"),
            {"j": started.json()["job_id"]},
        )
    ).one()
    assert (job.kind, job.correlation_id) == ("import.run", session_id)
    audited = (
        await db.execute(
            sa.text("select action from audit_logs where resource_id = :i order by created_at"),
            {"i": session_id},
        )
    ).scalars()
    assert list(audited) == ["import.upload", "import.start"]


async def test_a_file_over_the_limit_is_refused_before_it_is_read(api):
    async with api(BOTH) as client:
        response = await _upload(client, data=b"x" * (MAX_IMPORT_UPLOAD_BYTES + 1))
    assert response.status_code == 413


async def test_the_upload_limit_is_only_raised_for_the_upload_route(api):
    """Everything else keeps the 1 MiB body cap; the 20 MB allowance is for one route."""
    async with api(BOTH) as client:
        response = await client.put(
            "/api/v1/imports/sessions/00000000-0000-0000-0000-000000000001/mapping",
            content=b"x" * (2 * 1024 * 1024),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("../../etc/passwd.xlsx", "passwd.xlsx"),
        ("C:\\Users\\me\\prices.xlsx", "prices.xlsx"),
        ('a"b<c>d.xlsx', "a_b_c_d.xlsx"),
        ("منتجات.xlsx", "منتجات.xlsx"),
    ],
)
async def test_the_filename_is_stored_without_a_path_or_unsafe_characters(api, raw, stored):
    async with api(BOTH) as client:
        response = await _upload(client, name=raw)
    assert response.status_code == 201 and response.json()["file_name"] == stored


async def test_a_name_that_is_only_dots_is_refused(api):
    async with api(BOTH) as client:
        response = await _upload(client, name="...")
    assert response.status_code == 400
    assert "filename" in response.text


async def test_a_file_that_is_not_a_workbook_is_refused_with_a_message(api):
    async with api(BOTH) as client:
        response = await _upload(client, data=b"PK\x03\x04 not really a zip", name="a.xlsx")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_the_error_report_is_a_csv_that_excel_reads_in_arabic_and_cannot_run(api):
    csv_file = "Product ref,Name,Brand\n,,=HYPERLINK(1)\nقميص,,\n".encode("utf-8-sig")
    async with api(BOTH) as client:
        session_id = (await _upload(client, data=csv_file, name="p.csv")).json()["id"]
        await client.post(f"/api/v1/imports/sessions/{session_id}/validate")
        response = await client.get(f"/api/v1/imports/sessions/{session_id}/errors.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")  # the BOM that makes Excel show Arabic correctly
    assert "قميص" in text
    import csv as csv_module

    rows = list(csv_module.reader(io.StringIO(text.lstrip("\ufeff"))))
    # header, row 2 refused twice (no handle, no name), row 3 refused once: one line per reason
    assert len(rows) == 4
    assert rows[1][:5] == ["Products", "2", "product_ref", "required", "product_ref is required"]
    assert "Brand==HYPERLINK(1)" in rows[1][5]  # the merchant's own cell, shown as plain text


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2", "@SUM(A1)", "\tx", "\rx"])
def test_a_report_cell_that_could_run_as_a_formula_is_written_as_text(value):
    """Today no report column starts with the merchant's text, so this guards a future change."""
    from app.platform.imports.router import _csv_cell

    assert _csv_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["قميص", "TEE-1", "99.50", "", None, "a=b"])
def test_an_ordinary_report_cell_is_left_alone(value):
    from app.platform.imports.router import _csv_cell

    assert _csv_cell(value) == ("" if value is None else value)


async def test_the_upload_route_is_on_the_idempotency_list():
    from app.core.idempotency import IDEMPOTENT_PATHS

    assert any("/api/v1/imports/sessions".startswith(p) for p in IDEMPOTENT_PATHS)


# ---------------------------------------------------------------------------------------------
# The two size guards are independent layers (middleware, then the route's own stream cap). One
# test through the whole app cannot tell them apart, so each is exercised alone.
# ---------------------------------------------------------------------------------------------


async def _drive_asgi(app, method, path, body: bytes, *, declare_length: bool):
    """Send a request straight to an ASGI app and return (status, response body)."""
    sent, status, chunks = False, 0, []

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    headers = [(b"content-type", XLSX.encode())]
    if declare_length:
        headers.append((b"content-length", str(len(body)).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"filename=a.xlsx",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    return status, b"".join(chunks)


async def test_the_middleware_alone_allows_the_upload_route_20mb_and_nothing_else_more_than_1mb():
    from app.core.middleware import BodySizeLimitMiddleware

    seen = []

    async def downstream(scope, receive, send):
        seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    guard = BodySizeLimitMiddleware(downstream)
    five_mb = b"x" * (5 * 1024 * 1024)

    upload = "/api/v1/imports/sessions"
    other = "/api/v1/imports/sessions/00000000-0000-0000-0000-000000000001/mapping"
    assert (await _drive_asgi(guard, "POST", upload, five_mb, declare_length=True))[0] == 204
    assert (await _drive_asgi(guard, "POST", upload, five_mb, declare_length=False))[0] == 204
    over = b"x" * (MAX_IMPORT_UPLOAD_BYTES + 1)
    assert (await _drive_asgi(guard, "POST", upload, over, declare_length=True))[0] == 413
    assert (await _drive_asgi(guard, "PUT", other, five_mb, declare_length=True))[0] == 413
    # another POST, even one under the same prefix, keeps the 1 MiB cap
    validate = "/api/v1/imports/sessions/00000000-0000-0000-0000-000000000001/validate"
    assert (await _drive_asgi(guard, "POST", validate, five_mb, declare_length=True))[0] == 413
    assert (
        await _drive_asgi(guard, "POST", "/api/v1/imports/products", five_mb, declare_length=True)
    )[0] == 413
    assert (await _drive_asgi(guard, "GET", upload, five_mb, declare_length=True))[0] == 413
    assert seen == [upload, upload]  # only the two allowed uploads reached the app


async def test_the_route_stops_reading_a_body_that_lies_about_its_size(api, monkeypatch):
    """No Content-Length and an oversize stream: the route's own cap refuses it."""
    from app.platform.imports import router as imports_router

    monkeypatch.setattr(imports_router, "MAX_FILE_BYTES", 1000)
    async with api(BOTH) as client:

        async def body():
            for _ in range(5):
                yield b"x" * 400  # 2000 bytes in chunks, no declared length

        response = await client.post(
            "/api/v1/imports/sessions", params={"filename": "a.xlsx"}, content=body()
        )
    assert response.status_code == 413
