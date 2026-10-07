"""RLS isolation smoke test — proves tenant separation at the DATABASE layer.

Run from backend/ (after migrations + provision.py):
    .venv/bin/python scripts/rls_smoke_test.py

Creates two throwaway tenants and asserts:
  1. INSERT into a tenant table WITHOUT the GUC fails (FORCE RLS).
  2. INSERT bound to tenant A but writing tenant B's row fails (WITH CHECK).
  3. GUC=A sees only tenant A rows; GUC=B sees only tenant B rows.
  4. Cross-tenant SELECT by explicit id returns nothing.
Cleans up after itself.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402
from _bootstrap import load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"


async def main() -> int:
    settings = load_settings(script="scripts/rls_smoke_test.py")
    # The isolation test MUST run as the app runtime role (no bypassrls) —
    # running it as postgres would bypass RLS entirely and prove nothing.
    raw_dsn = settings.database_url_app_admin or ""
    if not raw_dsn:
        raise SystemExit("DATABASE_URL_APP_ADMIN missing — run scripts/provision.py first")
    # Session-pooler URL (:5432) for a real session (SET/RESET semantics).
    dsn = raw_dsn.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, timeout=20)
    results: list[tuple[str, str]] = []

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    uid: uuid.UUID | None = None

    async def set_guc(tenant_id: str | None) -> None:
        if tenant_id is None:
            await conn.execute("RESET app.tenant_id")
        else:
            await conn.execute(f"SET app.tenant_id = '{tenant_id}'")

    try:
        who = await conn.fetchrow(
            "SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        if who["rolbypassrls"]:
            raise SystemExit("test role has bypassrls — RLS test would be meaningless")
        print(f"testing as: {who['current_user']} (bypassrls=false)")
        await conn.execute(
            "INSERT INTO tenants (id, slug, name) VALUES ($1, $2, $3)",
            uuid.UUID(tenant_a),
            f"rls-test-a-{tenant_a[:8]}",
            "RLS Test A",
        )
        await conn.execute(
            "INSERT INTO tenants (id, slug, name) VALUES ($1, $2, $3)",
            uuid.UUID(tenant_b),
            f"rls-test-b-{tenant_b[:8]}",
            "RLS Test B",
        )

        # 1) no GUC -> INSERT must be rejected
        await set_guc(None)
        try:
            await conn.execute(
                "INSERT INTO customers (id, tenant_id, name) VALUES ($1, $2, $3)",
                uuid.uuid4(),
                uuid.UUID(tenant_a),
                "NoGUC",
            )
            results.append(("insert without GUC rejected", FAIL))
        except asyncpg.InsufficientPrivilegeError:
            results.append(("insert without GUC rejected", PASS))

        # 2) GUC=A but writing tenant B row -> WITH CHECK must reject
        await set_guc(tenant_a)
        try:
            await conn.execute(
                "INSERT INTO customers (id, tenant_id, name) VALUES ($1, $2, $3)",
                uuid.uuid4(),
                uuid.UUID(tenant_b),
                "CrossTenant",
            )
            results.append(("cross-tenant insert rejected", FAIL))
        except asyncpg.InsufficientPrivilegeError:
            results.append(("cross-tenant insert rejected", PASS))

        # seed one row per tenant
        ca = uuid.uuid4()
        cb = uuid.uuid4()
        await conn.execute(
            "INSERT INTO customers (id, tenant_id, name) VALUES ($1, $2, $3)",
            ca,
            uuid.UUID(tenant_a),
            "TenantA-Customer",
        )
        await set_guc(tenant_b)
        await conn.execute(
            "INSERT INTO customers (id, tenant_id, name) VALUES ($1, $2, $3)",
            cb,
            uuid.UUID(tenant_b),
            "TenantB-Customer",
        )

        # 3) GUC=A sees only A
        await set_guc(tenant_a)
        rows = await conn.fetch("SELECT id FROM customers")
        visible = {str(r["id"]) for r in rows}
        results.append(("GUC=A sees exactly its row", PASS if visible == {str(ca)} else FAIL))

        # 4) cross-tenant SELECT by id -> empty
        row = await conn.fetchrow("SELECT id FROM customers WHERE id = $1", cb)
        results.append(("GUC=A cannot select B row", PASS if row is None else FAIL))

        # 5) GUC=B mirror check
        await set_guc(tenant_b)
        rows = await conn.fetch("SELECT id FROM customers")
        visible = {str(r["id"]) for r in rows}
        results.append(("GUC=B sees exactly its row", PASS if visible == {str(cb)} else FAIL))

        # 6) tenant_users self-discovery: denied with no context, allowed via
        #    app.user_id (how login finds a user's memberships)
        await set_guc(None)
        uid = await conn.fetchval(
            "INSERT INTO users (id, email, password_hash, full_name) "
            "VALUES (gen_random_uuid(), $1, 'x', 'RLS Sanity') RETURNING id",
            f"rls-sanity-{uuid.uuid4().hex[:8]}@test.local",
        )
        denied = False
        try:
            await conn.execute(
                "INSERT INTO tenant_users (tenant_id, user_id, is_default) VALUES ($1, $2, false)",
                uuid.UUID(tenant_a),
                uid,
            )
        except asyncpg.InsufficientPrivilegeError:
            denied = True
        if not denied:
            results.append(("tenant_users insert with no context denied", FAIL))
        else:
            results.append(("tenant_users insert with no context denied", PASS))
            await conn.execute(f"SET app.user_id = '{uid}'")
            await conn.execute(
                "INSERT INTO tenant_users (tenant_id, user_id, is_default) VALUES ($1, $2, false)",
                uuid.UUID(tenant_a),
                uid,
            )
            results.append(("tenant_users self-access via app.user_id works", PASS))
    finally:
        # Tenants first (cascades tenant_users), then the sanity user row.
        await conn.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [tenant_a, tenant_b])
        if uid is not None:
            await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", [uid])
        await conn.close()

    print("\nRLS SMOKE TEST RESULTS")
    failed = 0
    for name, verdict in results:
        print(f"  [{verdict}] {name}")
        failed += verdict == FAIL
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
