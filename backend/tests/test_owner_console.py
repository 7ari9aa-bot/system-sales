"""Owner console + per-user channel access (DB-backed)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.modules.conversations.inbox import InboxQuery
from app.modules.conversations.models import Conversation
from app.modules.customers.models import Customer
from app.modules.identity.deps import AuthedUser, TenantContext
from app.modules.identity.models import User
from app.modules.platform.models import Integration
from app.modules.platform.routers.owner import owner_channel_matrix, owner_visitors
from app.modules.platform.routers.telemetry import TelemetryEventIn, ingest_telemetry
from app.modules.platform.services.channel_access import (
    allowed_providers,
    channel_status,
    set_access,
)


def _platform_ctx(db, tenant_ctx) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            is_platform_admin=True,
            is_active=True,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:read", "settings:write"},
    )


async def test_channel_access_defaults_to_enabled_and_revoke_locks(db, tenant_ctx):
    staff = User(
        email=f"staff-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="not-used",
        full_name="Staff Member",
    )
    db.add(staff)
    await db.flush()
    staff_id = staff.id
    await set_access(
        db,
        tenant_ctx.tenant_id,
        staff_id,
        "whatsapp",
        enabled=False,
        actor_user_id=tenant_ctx.user.id,
    )

    allowed = await allowed_providers(db, tenant_ctx.tenant_id, staff_id, "staff")
    assert "whatsapp" not in allowed
    assert "telegram" in allowed

    status = await channel_status(db, tenant_ctx.tenant_id, staff_id, "staff")
    whatsapp = next(row for row in status if row["provider"] == "whatsapp")
    assert whatsapp["enabled_for_me"] is False
    assert whatsapp["locked"] is True


async def test_inbox_channel_allowlist_is_a_sql_predicate(db, tenant_ctx):
    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Channel test")
    db.add(customer)
    await db.flush()
    db.add_all(
        [
            Conversation(
                tenant_id=tenant_ctx.tenant_id,
                customer_id=customer.id,
                channel="whatsapp",
                status="open",
            ),
            Conversation(
                tenant_id=tenant_ctx.tenant_id,
                customer_id=customer.id,
                channel="webchat",
                status="open",
            ),
        ]
    )
    await db.flush()

    rows = await InboxQuery.page(db, tenant_ctx.tenant_id, channels=["whatsapp"], limit=10)
    assert {row["channel"] for row in rows} == {"whatsapp"}

    none = await InboxQuery.page(db, tenant_ctx.tenant_id, channels=[], limit=10)
    assert none == []


async def test_public_telemetry_lands_and_owner_can_read_it(db, tenant_ctx):
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest-browser"},
    )
    result = await ingest_telemetry(
        request,
        db,
        TelemetryEventIn(
            visitor_id="visitor-12345678",
            session_id="session-12345678",
            event_type="page_view",
            path="/pricing",
            url="https://example.test/pricing",
            referrer="https://example.test/",
            metadata={"locale": "ar"},
        ),
    )
    assert result == {"ok": True}

    listed = await owner_visitors(_platform_ctx(db, tenant_ctx), limit=20, hours=24)
    assert listed.total >= 1
    assert any(item["path"] == "/pricing" for item in listed.items)
    assert any(item["event_type"] == "page_view" for item in listed.items)


async def test_owner_channel_matrix_reports_connection_truth(db, tenant_ctx):
    db.add(
        Integration(
            tenant_id=tenant_ctx.tenant_id,
            provider="whatsapp",
            kind="channel",
            status="active",
            config={
                "_connection": {
                    "verified_at": datetime.now(UTC).isoformat(),
                    "display_name": "Test Shop",
                }
            },
        )
    )
    await db.flush()

    matrix = await owner_channel_matrix(_platform_ctx(db, tenant_ctx), tenant_ctx.tenant_id)
    assert matrix.tenant_name == tenant_ctx.tenant.name
    assert matrix.members and matrix.members[0]["id"] == str(tenant_ctx.user.id)
    whatsapp = next(row for row in matrix.providers if row["provider"] == "whatsapp")
    assert whatsapp["connected"] is True
    assert whatsapp["lifecycle"] == "active"
