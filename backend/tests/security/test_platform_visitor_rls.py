"""RLS tests for the five platform & visitor tables — run as the sales_app role.

Each table in migration fe2026112602 has no ``tenant_id`` column, so the
standard ``tenant_isolation`` policy does not apply. These tests verify, as
the non-BYPASSRLS ``sales_app`` role (the one the API actually uses), that
each hand-written policy allows and denies exactly what the design says.

Skips loudly without ``DATABASE_URL_APP_ADMIN`` — see conftest.py.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import insert, select, text

from app.core.db import bind_tenant
from app.platform.billing.models import PlanPrice, TaxRate
from app.platform.identity.models import Role, Tenant, TenantUser, User
from app.platform.platform.models import (
    PlatformAnnouncement,
    PlatformAnnouncementDismissal,
    VisitorEvent,
)

_RLS_ERROR = "row-level security|policy|permission"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _rls_flags(db, table: str) -> tuple[bool, bool]:
    """Return (rls_enabled, rls_forced) for a table."""
    row = (
        await db.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table},
        )
    ).one()
    return bool(row[0]), bool(row[1])


async def _policy_names(db, table: str) -> set[str]:
    rows = (
        await db.execute(
            text(
                "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"
            ),
            {"t": table},
        )
    ).all()
    return {r[0] for r in rows}


async def _seed_tenant_owner(db, password_hash: str) -> tuple[Tenant, User]:
    """Create a tenant + owner so bind_tenant can set the GUC."""
    role = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="RLS Test")
    user = User(
        email=f"rls-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=password_hash,
        full_name="RLS Owner",
    )
    db.add_all([tenant, user])
    await db.flush()
    await db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)})
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    await db.flush()
    await bind_tenant(db, tenant.id)
    return tenant, user


# ---------------------------------------------------------------------------
# 1. visitor_events — INSERT allowed, SELECT gated on tenant GUC
# ---------------------------------------------------------------------------


class TestVisitorEventsRLS:
    async def test_rls_enabled_not_forced(self, db):
        enabled, forced = await _rls_flags(db, "visitor_events")
        assert enabled, "visitor_events must have RLS enabled"
        assert not forced, "visitor_events must NOT be forced (owner bypasses for analytics)"

    async def test_policies_exist(self, db):
        names = await _policy_names(db, "visitor_events")
        assert "visitor_events_read" in names
        assert "visitor_events_insert" in names

    async def test_insert_succeeds_without_tenant_guc(self, db):
        """The public telemetry endpoint writes with no tenant bound."""
        await db.execute(
            insert(VisitorEvent).values(
                visitor_id="testvisitor1234",
                session_id="testsession1234",
                event_type="page_view",
                path="/",
            )
        )
        await db.flush()  # no exception → INSERT allowed

    async def test_select_blocked_without_tenant_guc(self, db):
        """No tenant GUC → SELECT returns zero rows (RLS denies)."""
        await db.execute(text("SET LOCAL app.tenant_id = ''"))
        rows = (await db.execute(select(VisitorEvent))).scalars().all()
        assert rows == [], "SELECT must return 0 rows when no tenant GUC is bound"

    async def test_select_allowed_with_tenant_guc(self, db, owner_password_hash: str):
        """Tenant GUC bound → SELECT returns rows (owner console reads)."""
        await _seed_tenant_owner(db, owner_password_hash)
        await db.execute(
            insert(VisitorEvent).values(
                visitor_id="testvisitor5678",
                session_id="testsession5678",
                event_type="page_view",
                path="/home",
            )
        )
        await db.flush()
        rows = (await db.execute(select(VisitorEvent))).scalars().all()
        assert len(rows) >= 1, "SELECT must return rows when tenant GUC is bound"

    async def test_insert_allowed_with_empty_guc(self, db):
        """Empty-string GUC still allows INSERT (policy is WITH CHECK true)."""
        await db.execute(text("SET LOCAL app.tenant_id = ''"))
        await db.execute(
            insert(VisitorEvent).values(
                visitor_id="testvisitor9999",
                session_id="testsession9999",
                event_type="click",
                path="/btn",
            )
        )
        await db.flush()  # no exception → INSERT allowed


# ---------------------------------------------------------------------------
# 2. platform_announcements — SELECT for all, no writes for app role
# ---------------------------------------------------------------------------


class TestPlatformAnnouncementsRLS:
    async def test_rls_enabled_not_forced(self, db):
        enabled, forced = await _rls_flags(db, "platform_announcements")
        assert enabled, "platform_announcements must have RLS enabled"
        assert not forced, "platform_announcements must NOT be forced"

    async def test_select_policy_allows_all(self, db):
        names = await _policy_names(db, "platform_announcements")
        assert "announcements_read" in names

    async def test_insert_rejected(self, db):
        """sales_app has no INSERT policy → RLS denies the write."""
        with pytest.raises(Exception, match=_RLS_ERROR):
            await db.execute(insert(PlatformAnnouncement).values(title="Test", body="Test body"))
            await db.flush()


# ---------------------------------------------------------------------------
# 3. platform_announcement_dismissals — per-user isolation
# ---------------------------------------------------------------------------


class TestPlatformAnnouncementDismissalsRLS:
    async def test_rls_enabled_and_forced(self, db):
        enabled, forced = await _rls_flags(db, "platform_announcement_dismissals")
        assert enabled, "platform_announcement_dismissals must have RLS enabled"
        assert forced, "platform_announcement_dismissals must be FORCED"

    async def test_policy_exists(self, db):
        names = await _policy_names(db, "platform_announcement_dismissals")
        assert "dismissal_user_isolation" in names

    async def test_select_returns_zero_without_user_guc(self, db):
        """No app.user_id → NULLIF gives NULL → no rows match."""
        await db.execute(text("SET LOCAL app.user_id = ''"))
        rows = (await db.execute(select(PlatformAnnouncementDismissal))).all()
        assert rows == []

    async def test_select_returns_zero_for_wrong_user(self, db):
        """GUC set to user A, query for user B → 0 rows."""
        other = uuid.uuid4()
        await db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(other)})
        rows = (
            await db.execute(
                select(PlatformAnnouncementDismissal).where(
                    PlatformAnnouncementDismissal.user_id == uuid.uuid4()
                )
            )
        ).all()
        assert rows == []

    async def test_insert_rejected_for_wrong_user(self, db):
        """WITH CHECK (user_id = app.user_id) rejects a mismatched INSERT."""
        me = uuid.uuid4()
        someone_else = uuid.uuid4()
        await db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(me)})
        with pytest.raises(Exception, match=_RLS_ERROR):
            await db.execute(
                insert(PlatformAnnouncementDismissal).values(
                    announcement_id=uuid.uuid4(),
                    user_id=someone_else,
                )
            )
            await db.flush()


# ---------------------------------------------------------------------------
# 4. plan_prices — SELECT for all, no writes
# ---------------------------------------------------------------------------


class TestPlanPricesRLS:
    async def test_rls_enabled_and_forced(self, db):
        enabled, forced = await _rls_flags(db, "plan_prices")
        assert enabled, "plan_prices must have RLS enabled"
        assert forced, "plan_prices must be FORCED"

    async def test_select_policy_allows_all(self, db):
        names = await _policy_names(db, "plan_prices")
        assert "plan_prices_read" in names
        # Legacy sales_app_read must NOT survive (the migration dropped it and
        # provision.py no longer re-creates it).
        assert "sales_app_read" not in names

    async def test_select_works_without_tenant_guc(self, db):
        """The public marketing page reads plan_prices with no GUC bound."""
        await db.execute(text("SET LOCAL app.tenant_id = ''"))
        rows = (await db.execute(select(PlanPrice))).scalars().all()
        assert len(rows) > 0, "plan_prices must be readable without a tenant GUC (public page)"

    async def test_insert_rejected(self, db):
        """No INSERT policy + REVOKE'd privilege → write denied."""
        with pytest.raises(Exception, match=_RLS_ERROR):
            await db.execute(
                insert(PlanPrice).values(
                    plan_id=uuid.uuid4(),
                    country_code="EG",
                    currency="EGP",
                    price=100,
                    interval="month",
                    is_active=True,
                )
            )
            await db.flush()


# ---------------------------------------------------------------------------
# 5. tax_rates — SELECT for all, no writes
# ---------------------------------------------------------------------------


class TestTaxRatesRLS:
    async def test_rls_enabled_and_forced(self, db):
        enabled, forced = await _rls_flags(db, "tax_rates")
        assert enabled, "tax_rates must have RLS enabled"
        assert forced, "tax_rates must be FORCED"

    async def test_select_policy_allows_all(self, db):
        names = await _policy_names(db, "tax_rates")
        assert "tax_rates_read" in names
        assert "sales_app_read" not in names

    async def test_select_works_without_tenant_guc(self, db):
        """The public marketing page reads tax_rates with no GUC bound."""
        await db.execute(text("SET LOCAL app.tenant_id = ''"))
        rows = (await db.execute(select(TaxRate))).scalars().all()
        assert len(rows) > 0, "tax_rates must be readable without a tenant GUC"

    async def test_insert_rejected(self, db):
        """No INSERT policy + REVOKE'd privilege → write denied."""
        with pytest.raises(Exception, match=_RLS_ERROR):
            await db.execute(
                insert(TaxRate).values(
                    country_code="EG",
                    rate=0.14,
                    effective_from=date(2016, 9, 8),
                    label_ar="ضريبة",
                    label_en="VAT",
                    is_active=True,
                )
            )
            await db.flush()
