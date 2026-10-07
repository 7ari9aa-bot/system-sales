"""Auth-plane isolation (fd2026100410) — the two database audit findings, pinned.

F-1  the five global auth tables (users, refresh_tokens, password_reset_tokens,
     user_mfa_secrets, tenants) are FORCE RLS. The policies mirror the exact
     call patterns in identity/service.py + identity/deps.py: commands the app
     runs with a bound identity are scoped to it; pre-GUC possession lookups
     stay admitted (each such policy is documented as one app change away from
     being narrowed — the SECURITY DEFINER helpers from the migration are the
     adoption path). The open blocker this suite therefore does NOT assert:
     a no-GUC sales_app session can still READ users/refresh_tokens rows,
     because refresh()/logout() authenticate BY the token hash and
     deps.get_current_user reads users before anything is bound — a policy
     cannot see the query's WHERE argument. Every WRITE is scoped.
F-2  the RBAC reference plane (permissions, roles, role_permissions, plans)
     and the ops table alembic_version are SELECT-only for sales_app — writes
     are refused at the privilege layer. dr_policy is the audit's one REPORTED
     residual: DRService.get_policy lazily INSERTs its singleton from the
     platform health endpoint (and complete_restore_test stamps results on
     it), so freezing it without an app change would 500 that endpoint — its
     writability is pinned below so the gap stays visible, not accidental.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.modules.identity.service import AuthService

pytestmark = pytest.mark.usefixtures("db")


async def _expect_permission_denied(db, stmt) -> None:
    """Assert a refusal, shielded by a savepoint so the test transaction survives.

    A failed statement aborts the surrounding transaction; the savepoint keeps
    the fixture usable for the assertions that follow.
    """
    nested = await db.begin_nested()
    try:
        with pytest.raises(Exception, match="permission denied"):
            await db.execute(stmt)
    finally:
        await nested.rollback()


async def _raw_user(db, email: str | None = None) -> uuid.UUID:
    user_id = uuid.uuid4()
    await db.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, full_name, is_active) "
            "VALUES (:id, :email, 'x', 'Probe User', true)"
        ),
        {"id": str(user_id), "email": email or f"probe-{user_id.hex[:10]}@test.local"},
    )
    return user_id


async def _live_reset_token(db, user_id: uuid.UUID) -> uuid.UUID:
    row_id = uuid.uuid4()
    now = datetime.now(UTC)
    await db.execute(
        sa.text(
            "INSERT INTO password_reset_tokens "
            "(id, user_id, token_hash, encrypted_token, requested_at, expires_at, "
            " next_attempt_at) "
            "VALUES (:id, :uid, :th, 'enc', :req, :exp, :req)"
        ),
        {
            "id": str(row_id),
            "uid": str(user_id),
            "th": hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
            "req": now,
            "exp": now + timedelta(hours=1),
        },
    )
    return row_id


class TestUserRowIsolation:
    async def test_update_of_another_users_row_is_invisible(self, db, tenant_ctx):
        """With app.user_id bound to A, B's row is simply not there to update."""
        other = await _raw_user(db)
        result = await db.execute(
            sa.text("UPDATE users SET full_name = 'pwned' WHERE id = :u"),
            {"u": str(other)},
        )
        assert result.rowcount == 0, "a bound session reached another user's row"
        after = (
            await db.execute(
                sa.text("SELECT full_name FROM users WHERE id = :u"), {"u": str(other)}
            )
        ).scalar_one()
        assert after == "Probe User"

        own = await db.execute(
            sa.text("UPDATE users SET full_name = 'Renamed' WHERE id = :u"),
            {"u": str(tenant_ctx.user.id)},
        )
        assert own.rowcount == 1, "the self-row update must keep working"

    async def test_open_reset_flow_admits_the_password_change(self, db):
        """The reset flow binds no GUC: an OPEN reset request is the admission.

        The ORM consumes the token row BEFORE flushing the user write, so the
        policy keys on the immutable requested_at (window = the 1 hour token
        TTL), not on consumed_at. Single-use stays app-side; the policy bounds
        only the window — a user with no recent request stays unreachable.
        """
        stranger = await _raw_user(db)
        blocked = await db.execute(
            sa.text("UPDATE users SET password_hash = 'nope' WHERE id = :u"),
            {"u": str(stranger)},
        )
        assert blocked.rowcount == 0, "a user with no open reset flow is unreachable"

        user_id = await _raw_user(db)
        await _live_reset_token(db, user_id)
        granted = await db.execute(
            sa.text("UPDATE users SET password_hash = 'new-hash' WHERE id = :u"),
            {"u": str(user_id)},
        )
        assert granted.rowcount == 1, "an open reset flow must admit the reset write"

    async def test_reset_window_closes_after_the_token_ttl(self, db):
        """The admission expires with the token TTL — it is a window, not a grant."""
        user_id = await _raw_user(db)
        token_row = await _live_reset_token(db, user_id)
        await db.execute(
            sa.text(
                "UPDATE password_reset_tokens "
                "SET requested_at = now() - interval '2 hours' WHERE id = :r"
            ),
            {"r": str(token_row)},
        )
        expired = await db.execute(
            sa.text("UPDATE users SET password_hash = 'stale' WHERE id = :u"),
            {"u": str(user_id)},
        )
        assert expired.rowcount == 0, "the reset admission must close with the TTL"

    async def test_pre_guc_reset_flow_end_to_end(self, db):
        """AuthService.reset_password with NO GUC bound — production semantics.

        The ORM flushes the token's consumption UPDATE BEFORE the user write,
        which is exactly why the policy keys on the immutable requested_at
        instead of consumed_at. If the admission ever depends on flush order
        again, this test fails loudly instead of resetting passwords into an
        RLS error.
        """
        user_id = await _raw_user(db, email=f"reset-{uuid.uuid4().hex[:8]}@test.local")
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        await db.execute(
            sa.text(
                "INSERT INTO password_reset_tokens "
                "(id, user_id, token_hash, encrypted_token, requested_at, expires_at, "
                " next_attempt_at) "
                "VALUES (:id, :uid, :th, 'enc', :req, :exp, :req)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": str(user_id),
                "th": hashlib.sha256(token.encode()).hexdigest(),
                "req": now,
                "exp": now + timedelta(hours=1),
            },
        )
        await db.execute(sa.text("SELECT set_config('app.user_id', '', true)"))

        await AuthService.reset_password(db, token=token, password="replacement-pass-1")

        row = (
            await db.execute(
                sa.text("SELECT password_hash FROM users WHERE id = :u"), {"u": str(user_id)}
            )
        ).scalar_one()
        assert row != "x", "the pre-GUC reset path must still land the new hash"

    async def test_user_with_live_sessions_cannot_be_purged(self, db):
        user_id = await _raw_user(db)
        token_id = uuid.uuid4()
        await db.execute(
            sa.text(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at) "
                "VALUES (:id, :uid, :th, now() + interval '1 day')"
            ),
            {"id": str(token_id), "uid": str(user_id), "th": secrets.token_hex(32)},
        )
        blocked = await db.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": str(user_id)})
        assert blocked.rowcount == 0, "a user with live sessions must not be purgeable"

        await db.execute(
            sa.text("UPDATE refresh_tokens SET revoked_at = now() WHERE id = :r"),
            {"r": str(token_id)},
        )
        purged = await db.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": str(user_id)})
        assert purged.rowcount == 1, "teardown after revocation must keep working"


class TestRefreshTokenIsolation:
    async def test_only_dead_tokens_are_purgeable(self, db):
        user_id = await _raw_user(db)
        live = uuid.uuid4()
        await db.execute(
            sa.text(
                "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at) "
                "VALUES (:id, :uid, :th, now() + interval '1 day')"
            ),
            {"id": str(live), "uid": str(user_id), "th": secrets.token_hex(32)},
        )
        blocked = await db.execute(
            sa.text("DELETE FROM refresh_tokens WHERE id = :r"), {"r": str(live)}
        )
        assert blocked.rowcount == 0, "deleting a LIVE token must not match"

        await db.execute(
            sa.text("UPDATE refresh_tokens SET revoked_at = now() WHERE id = :r"),
            {"r": str(live)},
        )
        purged = await db.execute(
            sa.text("DELETE FROM refresh_tokens WHERE id = :r"), {"r": str(live)}
        )
        assert purged.rowcount == 1


class TestTenantIsolation:
    async def test_tenant_writes_require_a_bound_tenant(self, db):
        """No bound app.tenant_id -> no tenant row is writable; bound -> only that one."""
        other = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
            {"id": str(other), "slug": f"iso-{uuid.uuid4().hex[:10]}"},
        )
        blocked = await db.execute(
            sa.text("UPDATE tenants SET name = 'hijacked' WHERE id = :t"),
            {"t": str(other)},
        )
        assert blocked.rowcount == 0, "an unbound session mutated a tenant row"

        blocked_purge = await db.execute(
            sa.text("DELETE FROM tenants WHERE id = :t"), {"t": str(other)}
        )
        assert blocked_purge.rowcount == 0, "an unbound session deleted a tenant row"

        await bind_tenant(db, other)
        granted = await db.execute(
            sa.text("UPDATE tenants SET name = 'renamed' WHERE id = :t"),
            {"t": str(other)},
        )
        assert granted.rowcount == 1

        purged = await db.execute(sa.text("DELETE FROM tenants WHERE id = :t"), {"t": str(other)})
        assert purged.rowcount == 1

    async def test_platform_admin_guc_admits_the_break_glass_write(self, db):
        """§147: the break-glass route mutates tenants the admin is NOT a member of.

        The route's session has app.tenant_id bound to the ADMIN's own tenant,
        so only the app.is_platform_admin GUC can admit the cross-tenant
        target — and that GUC is set by deps.get_current_user from the
        DB-verified users row, never from the JWT. DELETE has no such branch:
        the offboarding purge is the one deleter and it binds the tenant.
        """
        other = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
            {"id": str(other), "slug": f"bg-{uuid.uuid4().hex[:10]}"},
        )
        try:
            await db.execute(sa.text("SELECT set_config('app.is_platform_admin', 'true', true)"))
            granted = await db.execute(
                sa.text("UPDATE tenants SET lifecycle_state = 'suspended' WHERE id = :t"),
                {"t": str(other)},
            )
            assert granted.rowcount == 1, "the break-glass admission must keep §147 alive"
        finally:
            await db.execute(sa.text("SELECT set_config('app.is_platform_admin', 'false', true)"))
        still_deleted_nothing = await db.execute(
            sa.text("DELETE FROM tenants WHERE id = :t"), {"t": str(other)}
        )
        assert still_deleted_nothing.rowcount == 0, "DELETE must stay tenant-bound only"


class TestReferencePlaneIsSelectOnly:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO roles (id, code, name) VALUES (gen_random_uuid(), 'ghost', 'Ghost')",
            "INSERT INTO permissions (id, code, resource, action) "
            "VALUES (gen_random_uuid(), 'ghost:write', 'ghost', 'write')",
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p LIMIT 0",
            "INSERT INTO plans (id, code, name) VALUES (gen_random_uuid(), 'ghost', 'Ghost')",
        ],
    )
    async def test_inserts_are_refused(self, db, sql):
        await _expect_permission_denied(db, sa.text(sql))

    async def test_mutations_are_refused(self, db):
        await _expect_permission_denied(
            db, sa.text("UPDATE plans SET price = 0 WHERE code = 'pro'")
        )
        await _expect_permission_denied(
            db, sa.text("DELETE FROM permissions WHERE code LIKE 'ghost%'")
        )

    async def test_reads_still_work(self, db):
        codes = (await db.execute(sa.text("SELECT count(*) FROM roles"))).scalar_one()
        assert codes >= 1, "the seeded roles must stay readable"

    async def test_alembic_version_is_not_writable(self, db):
        await _expect_permission_denied(db, sa.text("UPDATE alembic_version SET version_num = 'x'"))
        await _expect_permission_denied(db, sa.text("DELETE FROM alembic_version"))

    async def test_dr_policy_writes_remain_open_pending_app_change(self, db):
        """The audit's REPORTED residual, pinned so it is visible, not forgotten.

        DRService.get_policy lazily INSERTs the dr_policy singleton on the
        first platform health read (platform/router.py -> check_dr_health) and
        complete_restore_test stamps the last test result on the same row, so
        the fd2026100410 freeze deliberately skips this table. Freezing it
        requires seeding the singleton in provision and moving the stamp off
        the runtime role first — until then this row's writability is the
        documented exception, not an oversight.
        """
        row_id = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO dr_policy (id, rpo_minutes) VALUES (:id, 5)"),
            {"id": str(row_id)},
        )
        stamped = await db.execute(
            sa.text("UPDATE dr_policy SET rpo_minutes = 7 WHERE id = :id"),
            {"id": str(row_id)},
        )
        assert stamped.rowcount == 1, (
            "dr_policy writability is the reported residual — if this fails "
            "because it got frozen, update the fd2026100410 report"
        )


class TestSchemaPosture:
    async def test_auth_tables_are_force_rls_with_policies(self, db):
        rows = (
            await db.execute(
                sa.text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policies p "
                    " WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
                ),
                {
                    "tables": [
                        "users",
                        "refresh_tokens",
                        "password_reset_tokens",
                        "user_mfa_secrets",
                        "tenants",
                    ]
                },
            )
        ).all()
        assert len(rows) == 5
        for row in rows:
            assert row.relrowsecurity and row.relforcerowsecurity, f"{row.relname} not FORCE RLS"
            assert row.policies >= 1, f"{row.relname} has no policies"
