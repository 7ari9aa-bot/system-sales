"""Owner console "Websites" section: the gate, the input checks, the audit trail.

Same harness as ``test_platform_http_surface``: the real app, auth and session swapped, and the
platform client replaced by a recorder so the tests can say what WOULD reach Fihrist Sites.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.modules.platform.services import sites_platform as sp

BASE = "/api/v1/owner/sites-platform"
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
SITE = "3bcfd644-e959-4a69-8189-d0e4da86a14d"


class _Session:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("the sites-platform section must not query Fihrist's own database")


class _Platform:
    """Stands in for the platform client and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.changed = 1

    async def select(self, table, **kw):
        self.calls.append(("select", (table,), kw))
        if kw.get("count_only"):
            return 3
        return {
            "sites": [
                {"id": SITE, "slug": "a", "name": "A", "design": "funny-baby", "status": "active"}
            ],
            "fihrist_links": [{"site_id": SITE, "key_hint": "abcd", "sync_enabled": True}],
            "designs": [{"key": "funny-baby", "name": "x", "is_listed": True, "sort_order": 1}],
        }.get(table, [{"x": 1}])

    async def update(self, table, match, values):
        self.calls.append(("update", (table, match), values))
        return self.changed


def _app(*, admin: bool, platform: _Platform, monkeypatch):
    session = _Session()
    user = AuthedUser(id=USER, tenant_id=TENANT, role_code="owner", is_platform_admin=admin)
    ctx = TenantContext(
        session=session, user=user, tenant_id=TENANT, role_code="owner", permission_codes=set()
    )
    app = create_app()

    async def _db():
        yield session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _db
    for name in ("select", "update"):
        monkeypatch.setattr(sp, name, getattr(platform, name))
    monkeypatch.setattr(sp, "is_configured", lambda: True)
    return app, session


async def _call(method, path, *, admin=True, body=None, params=None, monkeypatch, platform=None):
    platform = platform or _Platform()
    app, session = _app(admin=admin, platform=platform, monkeypatch=monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", timeout=10) as c:
        r = await c.request(method, BASE + path, json=body, params=params)
    return r, platform, session


def _operations() -> list[tuple[str, str]]:
    paths = create_app().openapi()["paths"]
    return [
        (m.upper(), p.removeprefix(BASE)) for p, v in paths.items() if p.startswith(BASE) for m in v
    ]


def _concrete(path: str) -> str:
    return (
        path.replace("{key}", "funny-baby").replace("{slug}", "privacy").replace("{site_id}", SITE)
    )


_BODY = {
    "PATCH": {"is_listed": True},
    "PUT": {"value": 5},
    "POST": {"publish": True},
}


def test_the_section_has_the_expected_surface() -> None:
    assert len(_operations()) == 14  # an added/removed route must be a deliberate edit here


async def test_every_operation_refuses_a_non_platform_admin(monkeypatch) -> None:
    """Read from the live OpenAPI, so a route added later without the gate fails this test."""
    for method, path in _operations():
        body = _BODY.get(method)
        if method == "PUT" and "/legal/" in path:
            body = {"title": "t", "sections": [{"title": "a", "body": "b"}]}
        if method == "PATCH" and "/sites/" in path:
            body = {"status": "suspended"}
        if method == "PATCH" and "/fihrist-links/" in path:
            body = {"sync_enabled": False}
        r, platform, _ = await _call(
            method, _concrete(path), admin=False, body=body, monkeypatch=monkeypatch
        )
        assert r.status_code in (401, 403), (method, path, r.status_code)
        assert platform.calls == [], (method, path, "reached the platform without the gate")


async def test_not_configured_answers_503_not_a_stack_trace(monkeypatch) -> None:
    async def off(*_a, **_k):
        raise sp.SitesPlatformNotConfigured("x")

    app, _ = _app(admin=True, platform=_Platform(), monkeypatch=monkeypatch)
    monkeypatch.setattr(sp, "select", off)
    monkeypatch.setattr(sp, "update", off)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for path in (
            "/purchases",
            "/designs",
            "/limits",
            "/legal",
            "/fihrist-links",
            "/sites",
            "/audit",
        ):
            r = await c.get(BASE + path)
            assert r.status_code == 503, (path, r.status_code)
            assert "not configured" in r.json()["detail"].lower()
        r = await c.patch(BASE + "/designs/funny-baby", json={"is_listed": True})
        assert r.status_code == 503


async def test_status_reports_whether_it_is_configured(monkeypatch) -> None:
    r, _, _ = await _call("GET", "/status", monkeypatch=monkeypatch)
    assert r.status_code == 200 and r.json() == {"configured": True}


async def test_a_bad_id_or_key_never_reaches_the_platform(monkeypatch) -> None:
    cases = [
        ("PATCH", "/designs/A%26b", {"is_listed": True}),
        ("PATCH", "/designs/" + "a" * 70, {"is_listed": True}),
        ("PATCH", f"/fihrist-links/{SITE}x", {"sync_enabled": False}),
        ("PATCH", "/fihrist-links/not-a-uuid", {"sync_enabled": False}),
        ("PATCH", "/sites/1%27%20or%20%271", {"status": "suspended"}),
        ("PUT", "/limits/Max-Products", {"value": 5}),
        ("PUT", "/limits/%26a%3Db", {"value": 5}),
    ]
    for method, path, body in cases:
        r, platform, _ = await _call(method, path, body=body, monkeypatch=monkeypatch)
        assert r.status_code in (400, 404, 422), (path, r.status_code)
        assert platform.calls == [], (path, platform.calls)


async def test_values_are_validated_before_they_reach_the_platform(monkeypatch) -> None:
    bad = [
        ("PATCH", "/designs/funny-baby", {"price_egp": -1}),
        ("PATCH", "/designs/funny-baby", {"price_egp": 10**9}),
        ("PATCH", "/designs/funny-baby", {}),
        (
            "PATCH",
            "/designs/funny-baby",
            {"origin": "https://evil"},
        ),  # not a field: ignored => nothing to change
        ("PUT", "/limits/max_products", {"value": -1}),
        ("PUT", "/limits/max_products", {"value": "lots"}),
        ("PATCH", f"/sites/{SITE}", {"status": "deleted"}),
        ("PATCH", f"/sites/{SITE}", {"status": "banned"}),
        ("PUT", "/legal/privacy", {"title": "  ", "sections": [{"title": "a", "body": "b"}]}),
        ("PUT", "/legal/privacy", {"title": "t", "sections": []}),
        ("PUT", "/legal/privacy", {"title": "t", "sections": [{"title": "a", "body": ""}]}),
        ("PUT", "/legal/privacy", {"title": "t", "sections": [{"title": "a", "body": "b"}] * 41}),
        ("PUT", "/legal/nope", {"title": "t", "sections": [{"title": "a", "body": "b"}]}),
        ("PUT", "/legal/__proto__", {"title": "t", "sections": [{"title": "a", "body": "b"}]}),
        ("POST", "/legal/nope/publish", {"publish": True}),
    ]
    for method, path, body in bad:
        r, platform, _ = await _call(method, path, body=body, monkeypatch=monkeypatch)
        assert r.status_code in (400, 404, 422), (path, body, r.status_code)
        assert platform.calls == [], (path, body, platform.calls)


async def test_a_design_edit_sends_only_what_was_asked_and_is_audited(monkeypatch) -> None:
    r, platform, session = await _call(
        "PATCH", "/designs/funny-baby", body={"price_egp": 2500}, monkeypatch=monkeypatch
    )
    assert r.status_code == 200 and r.json() == {"ok": True, "changed": 1}
    assert platform.calls == [("update", ("designs", {"key": "funny-baby"}), {"price_egp": 2500})]
    assert len(session.added) == 1 and session.commits == 1
    row = session.added[0]
    assert row.action == "sites_platform.design.edit" and row.resource_id == "funny-baby"


async def test_a_rejected_or_missing_target_writes_no_audit_row(monkeypatch) -> None:
    gone = _Platform()
    gone.changed = 0
    r, _, session = await _call(
        "PATCH",
        "/designs/funny-baby",
        body={"is_listed": False},
        monkeypatch=monkeypatch,
        platform=gone,
    )
    assert r.status_code == 404 and session.added == []


async def test_a_legal_edit_goes_back_to_draft_and_strips_nul(monkeypatch) -> None:
    body = {
        "title": "  عنوان  ",
        "summary": "s",
        "sections": [{"title": "a\x00", "body": "<b>x</b>\x00"}],
    }
    r, platform, session = await _call("PUT", "/legal/privacy", body=body, monkeypatch=monkeypatch)
    assert r.status_code == 200
    (_, (table, match), values) = platform.calls[0]
    assert table == "platform_legal" and match == {"slug": "privacy"}
    assert values["is_draft"] is True  # an edit is never public unseen
    assert values["title"] == "عنوان" and values["owner_edited_at"]
    assert values["sections"] == [
        {"title": "a", "body": "<b>x</b>"}
    ]  # NUL gone, markup kept as text
    assert session.added[0].action == "sites_platform.legal.edit"


async def test_publish_and_unpublish_flip_the_draft_flag(monkeypatch) -> None:
    r, platform, session = await _call(
        "POST", "/legal/cookies/publish", body={"publish": True}, monkeypatch=monkeypatch
    )
    assert r.status_code == 200
    assert platform.calls[0][2]["is_draft"] is False and platform.calls[0][2]["published_at"]
    assert session.added[0].action == "sites_platform.legal.publish"
    r, platform, session = await _call(
        "POST", "/legal/cookies/publish", body={"publish": False}, monkeypatch=monkeypatch
    )
    assert platform.calls[0][2]["is_draft"] is True
    assert session.added[0].action == "sites_platform.legal.unpublish"


async def test_the_fihrist_links_list_never_asks_for_the_encrypted_key(monkeypatch) -> None:
    r, platform, _ = await _call("GET", "/fihrist-links", monkeypatch=monkeypatch)
    assert r.status_code == 200
    assert "key_ciphertext" not in r.text
    assert r.json()["items"][0]["site"]["slug"] == "a"


async def test_site_counts_are_numbers_only(monkeypatch) -> None:
    r, platform, _ = await _call("GET", "/sites", monkeypatch=monkeypatch)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["products"] == item["orders"] == item["coupons"] == item["messages"] == 3
    for _kind, (table, *_), _kw in [(c[0], c[1], c[2]) for c in platform.calls]:
        assert table in {"sites", "products", "orders", "coupons", "contact_messages"}
    assert not any(w in r.text for w in ("customer_name", "phone", "address"))


async def test_there_is_no_route_to_delete_or_to_confirm_a_payment() -> None:
    ops = _operations()
    assert not any(m == "DELETE" for m, _ in ops)
    assert not any("confirm" in p or "delete" in p for _, p in ops)


@pytest.mark.parametrize("path", ["/purchases", "/audit"])
async def test_list_limits_are_bounded(path, monkeypatch) -> None:
    for bad in (0, -1, 201, "x"):
        r, platform, _ = await _call("GET", path, params={"limit": bad}, monkeypatch=monkeypatch)
        assert r.status_code == 422 and platform.calls == [], (path, bad)


async def test_every_write_leaves_exactly_one_audit_row_with_its_own_action(monkeypatch) -> None:
    """One audit row per successful write, named for what happened. A write that forgets to
    audit (or audits under the wrong name) is invisible to the owner, so each is pinned here."""
    writes = [
        ("PATCH", f"/sites/{SITE}", {"status": "suspended"}, "sites_platform.site.status", SITE),
        ("PATCH", f"/sites/{SITE}", {"status": "active"}, "sites_platform.site.status", SITE),
        ("PUT", "/limits/max_products", {"value": 600}, "sites_platform.limit.set", "max_products"),
        (
            "PATCH",
            f"/fihrist-links/{SITE}",
            {"sync_enabled": False},
            "sites_platform.fihrist.sync",
            SITE,
        ),
        (
            "PATCH",
            "/designs/funny-baby",
            {"is_listed": False},
            "sites_platform.design.edit",
            "funny-baby",
        ),
    ]
    for method, path, body, action, target in writes:
        r, platform, session = await _call(method, path, body=body, monkeypatch=monkeypatch)
        assert r.status_code == 200, (path, body, r.status_code, r.text)
        assert len(platform.calls) == 1 and platform.calls[0][0] == "update", (path, platform.calls)
        assert len(session.added) == 1, (path, "audit rows:", len(session.added))
        assert session.added[0].action == action and session.added[0].resource_id == target, (
            path,
            session.added[0].action,
        )
        assert session.commits == 1


async def test_a_site_status_change_sends_exactly_the_requested_status(monkeypatch) -> None:
    r, platform, _ = await _call(
        "PATCH", f"/sites/{SITE}", body={"status": "suspended"}, monkeypatch=monkeypatch
    )
    assert platform.calls == [("update", ("sites", {"id": SITE}), {"status": "suspended"})]
    r, platform, _ = await _call(
        "PUT", "/limits/max_products", body={"value": 7}, monkeypatch=monkeypatch
    )
    assert platform.calls == [
        ("update", ("platform_limits", {"key": "max_products"}), {"value": 7})
    ]
