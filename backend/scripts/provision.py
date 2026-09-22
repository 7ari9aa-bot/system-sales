"""One-shot database provisioning: RLS policies + seed data. Idempotent.

RLS strategy (defense in depth — the app ALSO enforces tenant scoping):
- Every table carrying tenant_id gets RLS ENABLED + FORCED, with a single
  policy keyed on current_setting('app.tenant_id')::uuid. With FORCE, even the
  table owner must set the GUC per transaction — bind_tenant() does exactly
  that (SET LOCAL, pooler-safe).
- tenant_users is FORCE-EXEMPT: it is how we DISCOVER a user's memberships
  before any tenant context exists (chicken-and-egg). App-layer rules cover it.
- user_location_access (spec §151) has no tenant_id of its own: its RLS is a
  second, user-keyed policy (location_access) in the tenant_users style — a
  member only reaches locations they were explicitly granted.
- audit_logs: RLS enabled, NOT forced (platform-level actions write NULL
  tenant_id); policy still applies to non-owner roles.
- customer_tags has no tenant_id column (association) — its policy resolves
  tenancy through the customers parent row.
- outbox_events / idempotency_keys are cross-tenant system tables: no RLS.

Run from backend/ after migrations:
    .venv/bin/python scripts/provision.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402
from _bootstrap import load_settings  # noqa: E402

from app.core.model_registry import Base  # noqa: E402

GUC = "app.tenant_id"
USER_GUC = "app.user_id"

FORCE_EXEMPT: set[str] = set()  # nothing exempt — FORCE applies to all tenant tables
NO_TENANT_TABLES = {
    "outbox_events",
    "idempotency_keys",
    "plans",
    "refresh_tokens",  # user-scoped, not tenant-scoped
    # NOTE: `scheduled_jobs` and `webhook_events` used to be listed here as
    # "system plumbing". Production disagreed — both are FORCE RLS with a
    # tenant_isolation policy — and that divergence hid a live bug: the
    # scheduler's unbound INSERT was rejected in production while succeeding in
    # CI, so no test could see it. Migration d5e6f7a8b9c0 aligns the schemas;
    # removing them here keeps fresh provisions consistent with both.
}  # system/global
# Tables that carry a nullable tenant_id but allow platform-level NULL rows.
NULLABLE_TENANT_TABLES = {"security_events"}  # audit_logs handled separately below
ASSOCIATION_VIA = {"customer_tags": ("customers", "customer_id")}


def _tenant_tables() -> list[str]:
    names = []
    for table in Base.metadata.sorted_tables:
        if table.name in NO_TENANT_TABLES:
            continue
        if "tenant_id" in table.columns:
            names.append(table.name)
    return names


def _rls_statements() -> list[str]:
    stmts: list[str] = []
    guard = f"NULLIF(current_setting('{GUC}', true), '')::uuid"

    for name in _tenant_tables():
        stmts.append(f'ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY;')
        if name not in FORCE_EXEMPT:
            stmts.append(f'ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY;')
        stmts.append(f'DROP POLICY IF EXISTS tenant_isolation ON public.{name};')
        if name == "tenant_users":
            # Membership discovery at login: a user may see/claim their own
            # rows via app.user_id before any tenant context exists.
            user_guard = f"NULLIF(current_setting('{USER_GUC}', true), '')::uuid"
            stmts.append(
                f'CREATE POLICY tenant_isolation ON public.{name} '
                f'USING (tenant_id = {guard} OR user_id = {user_guard}) '
                f'WITH CHECK (tenant_id = {guard} OR user_id = {user_guard});'
            )
        else:
            stmts.append(
                f'CREATE POLICY tenant_isolation ON public.{name} '
                f'USING (tenant_id = {guard}) WITH CHECK (tenant_id = {guard});'
            )

    for name, (parent, fk_col) in ASSOCIATION_VIA.items():
        stmts.append(f'ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY;')
        stmts.append(f'ALTER TABLE public.{name} FORCE ROW LEVEL SECURITY;')
        stmts.append(f'DROP POLICY IF EXISTS tenant_isolation ON public.{name};')
        stmts.append(
            f'CREATE POLICY tenant_isolation ON public.{name} '
            f'USING (EXISTS (SELECT 1 FROM public.{parent} p WHERE p.id = {name}.{fk_col} '
            f'AND p.tenant_id = {guard})) '
            f'WITH CHECK (EXISTS (SELECT 1 FROM public.{parent} p WHERE p.id = {name}.{fk_col} '
            f'AND p.tenant_id = {guard}));'
        )

    # user_location_access (spec §151): tenant-scoping comes from the location
    # row, so the policy keys on the request user (tenant_users-style user
    # GUC) instead of app.tenant_id. The general tenant_isolation policy is
    # untouched; this is the only table with this variant. The owner OR-clause
    # lets the §151 Q3 admin API manage OTHER members' grants; kept identical
    # to migration f151ee151ee1 so an already-migrated database converges.
    ula = "user_location_access"
    if ula in Base.metadata.tables:
        ula_user_guard = f"NULLIF(current_setting('{USER_GUC}', true), '')::uuid"
        ula_self = f"user_id = {ula_user_guard}"
        ula_admin = (
            "EXISTS (SELECT 1 FROM public.locations l "
            "JOIN public.tenant_users tu ON tu.tenant_id = l.tenant_id "
            "JOIN public.roles r ON r.id = tu.role_id "
            f"WHERE l.id = {ula}.location_id AND tu.user_id = {ula_user_guard} "
            "AND r.code = 'owner')"
        )
        stmts.append(f'ALTER TABLE public.{ula} ENABLE ROW LEVEL SECURITY;')
        stmts.append(f'ALTER TABLE public.{ula} FORCE ROW LEVEL SECURITY;')
        stmts.append(f'DROP POLICY IF EXISTS location_access ON public.{ula};')
        stmts.append(
            f'CREATE POLICY location_access ON public.{ula} '
            f'USING ({ula_self} OR {ula_admin}) '
            f'WITH CHECK ({ula_self} OR {ula_admin});'
        )

    audit = "audit_logs"
    stmts.append(f'ALTER TABLE public.{audit} ENABLE ROW LEVEL SECURITY;')
    stmts.append(f'ALTER TABLE public.{audit} NO FORCE ROW LEVEL SECURITY;')
    stmts.append(f'DROP POLICY IF EXISTS tenant_isolation ON public.{audit};')
    stmts.append(
        f'CREATE POLICY tenant_isolation ON public.{audit} '
        f'USING (tenant_id IS NULL OR tenant_id = {guard}) '
        f'WITH CHECK (tenant_id IS NULL OR tenant_id = {guard});'
    )
    # security_events: pre-auth paths (login failure) write NULL-tenant rows;
    # a strict tenant_id = guard policy would silently reject them (S8).
    se = "security_events"
    if se in Base.metadata.tables:
        stmts.append(f'ALTER TABLE public.{se} ENABLE ROW LEVEL SECURITY;')
        stmts.append(f'ALTER TABLE public.{se} FORCE ROW LEVEL SECURITY;')
        stmts.append(f'DROP POLICY IF EXISTS tenant_isolation ON public.{se};')
        stmts.append(
            f'CREATE POLICY tenant_isolation ON public.{se} '
            f'USING (tenant_id IS NULL OR tenant_id = {guard}) '
            f'WITH CHECK (tenant_id IS NULL OR tenant_id = {guard});'
        )
    return stmts


# Channel webhooks arrive BEFORE any tenant is known, so tenant resolution
# cannot read `integrations` directly — that table is FORCE-RLS and the GUC is
# not bound yet, so a plain SELECT returns zero rows and every inbound webhook
# is acknowledged while ingesting nothing. SECURITY DEFINER runs the lookup as
# the table owner and returns ONLY the tenant id, so provider credentials in
# integrations.config never leave the table. search_path is pinned — mandatory
# for SECURITY DEFINER. Kept identical to migration b2c3d4e5f6a7 so an
# already-provisioned database converges.
CHANNEL_TENANT_FN_SQL = """
CREATE OR REPLACE FUNCTION public.resolve_channel_tenant(p_provider text, p_key text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT i.tenant_id
      FROM public.integrations i
     WHERE i.provider = p_provider
       AND i.kind = 'channel'
       AND i.status IN ('active', 'connected')
       AND p_key IN (
             i.config->>'phone_number_id',
             i.config->>'bot_id',
             i.config->>'public_key',
             i.config->>'account_id'
           )
     ORDER BY i.created_at
     LIMIT 1
$fn$;
"""

# asyncpg's extended-query protocol accepts ONE statement per execute, so the
# REVOKE is issued separately (same reason as the migration).
CHANNEL_TENANT_FN_REVOKE = (
    "REVOKE ALL ON FUNCTION public.resolve_channel_tenant(text, text) FROM PUBLIC;"
)


ROLES = [
    ("owner", "Owner", "Full access to the tenant"),
    ("manager", "Manager", "Operational access, no billing/settings writes"),
    ("staff", "Staff", "Frontline: conversations, customers, orders"),
]

RESOURCES = [
    "customers", "conversations", "products", "inventory", "orders",
    "marketing", "ai", "analytics", "settings", "billing",
]
ACTIONS = ["read", "write"]

ROLE_MATRIX: dict[str, list[str]] = {
    "owner": [f"{r}:{a}" for r in RESOURCES for a in ACTIONS],
    "manager": [
        f"{r}:{a}" for r in RESOURCES for a in ACTIONS
        if not (r in ("settings", "billing") and a == "write")
    ],
    "staff": [
        "customers:read", "customers:write",
        "conversations:read", "conversations:write",
        "products:read", "inventory:read",
        "orders:read", "orders:write",
        "analytics:read",
    ],
}

ALL_CHANNELS = ["whatsapp", "instagram", "messenger", "telegram", "webchat"]

PLANS = [
    (
        "starter",
        "Starter",
        0,
        {"max_users": 3, "channels": ["whatsapp", "webchat"], "ai_agents": 1},
    ),
    ("pro", "Pro", 1500, {"max_users": 15, "channels": ALL_CHANNELS, "ai_agents": 10}),
    (
        "enterprise",
        "Enterprise",
        0,
        {"max_users": None, "channels": "*", "ai_agents": None, "custom": True},
    ),
]


async def setup_app_role(conn: asyncpg.Connection, password: str) -> None:
    """Create the application DB role WITHOUT bypassrls so RLS truly binds it.

    Supabase's `postgres` role has BYPASSRLS — fine for migrations/ops, wrong
    for the app runtime. The API and workers connect as `sales_app` instead;
    on the Supavisor pooler its username is `sales_app.<project-ref>`.
    """
    await conn.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            CREATE ROLE sales_app LOGIN PASSWORD NULL;
          END IF;
        END
        $$;
        """
    )
    # ALTER ROLE is a utility statement — no bind params; quote defensively.
    safe_password = password.replace("'", "''")
    await conn.execute(f"ALTER ROLE sales_app LOGIN PASSWORD '{safe_password}'")
    grants = [
        "GRANT USAGE ON SCHEMA public TO sales_app",
        "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sales_app",
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sales_app",
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "GRANT ALL ON TABLES TO sales_app",
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        "GRANT ALL ON SEQUENCES TO sales_app",
    ]
    for stmt in grants:
        await conn.execute(stmt)
    print("app role: sales_app ready (no bypassrls, full table grants)")


async def seed(conn: asyncpg.Connection) -> None:
    for code, name, description in ROLES:
        await conn.execute(
            """
            INSERT INTO roles (id, code, name, description)
            VALUES (gen_random_uuid(), $1, $2, $3)
            ON CONFLICT (code) DO NOTHING
            """,
            code, name, description,
        )

    for resource in RESOURCES:
        for action in ACTIONS:
            code = f"{resource}:{action}"
            await conn.execute(
                """
                INSERT INTO permissions (id, code, resource, action)
                VALUES (gen_random_uuid(), $1, $2, $3)
                ON CONFLICT (code) DO NOTHING
                """,
                code, resource, action,
            )

    for role_code, allowed in ROLE_MATRIX.items():
        await conn.execute(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r, permissions p
            WHERE r.code = $1 AND p.code = ANY($2::text[])
            ON CONFLICT DO NOTHING
            """,
            role_code, allowed,
        )

    for code, name, price, features in PLANS:
        row = await conn.fetchrow("SELECT id FROM plans WHERE code = $1", code)
        if row is None:
            await conn.execute(
                """
                INSERT INTO plans (id, code, name, price, currency, features)
                VALUES (gen_random_uuid(), $1, $2, $3, 'EGP', $4::jsonb)
                """,
                code, name, price, json.dumps(features),
            )

    counts = await conn.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM roles) AS roles,
          (SELECT count(*) FROM permissions) AS permissions,
          (SELECT count(*) FROM role_permissions) AS role_permissions,
          (SELECT count(*) FROM plans) AS plans
        """
    )
    print(
        f"seeded: roles={counts['roles']} permissions={counts['permissions']} "
        f"role_permissions={counts['role_permissions']} plans={counts['plans']}"
    )


async def main() -> None:
    settings = load_settings(script="scripts/provision.py")
    url = settings.database_url_admin or settings.database_url
    # asyncpg wants the plain postgres:// form without the +asyncpg suffix.
    dsn = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql.iixxqitfopsgvaheedlg", "postgres.iixxqitfopsgvaheedlg"
    )
    # Reuse the existing password when present — rotating on every run
    # breaks already-deployed services using the previous DSN.
    env_path = Path(__file__).resolve().parent.parent / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_URL_APP="):
                try:
                    existing = line.split("=", 1)[1].split("@")[0].split(":")[-1]
                except Exception:
                    existing = {}
    app_password = existing or settings.sales_app_db_password or _random_password()
    conn = await asyncpg.connect(dsn, timeout=20)
    try:
        await setup_app_role(conn, app_password)
        statements = _rls_statements()
        for stmt in statements:
            await conn.execute(stmt)
        print(f"RLS applied: {len(statements)} statements")
        # Pre-tenant tenant resolution must not depend on the RLS GUC (see
        # CHANNEL_TENANT_FN_SQL) — created here too so a database provisioned
        # without the migration still gets it.
        await conn.execute(CHANNEL_TENANT_FN_SQL)
        await conn.execute(CHANNEL_TENANT_FN_REVOKE)
        await conn.execute(
            "GRANT EXECUTE ON FUNCTION public.resolve_channel_tenant(text, text) "
            "TO sales_app"
        )
        await seed(conn)
    finally:
        await conn.close()
    _write_app_password(app_password)


def _random_password() -> str:
    import secrets

    return secrets.token_urlsafe(24)


def _write_app_password(password: str) -> None:
    """Persist the app-role DSNs into .env so the runtime picks them up."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    ref = "iixxqitfopsgvaheedlg"
    app_url = (
        f"DATABASE_URL_APP=postgresql+asyncpg://sales_app.{ref}:{password}"
        f"@aws-1-eu-west-1.pooler.supabase.com:6543/postgres\n"
    )
    admin_url = (
        f"DATABASE_URL_APP_ADMIN=postgresql+asyncpg://sales_app.{ref}:{password}"
        f"@aws-1-eu-west-1.pooler.supabase.com:5432/postgres\n"
    )
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    lines = [
        line
        for line in lines
        if not line.startswith(("DATABASE_URL=", "DATABASE_URL_APP=", "DATABASE_URL_APP_ADMIN="))
    ]
    lines += [
        f"DATABASE_URL={app_url.split('=', 1)[1]}",
        app_url.rstrip("\n"),
        admin_url.rstrip("\n"),
    ]
    env_path.write_text("\n".join(lines) + "\n")
    print("app role DSNs written to .env (DATABASE_URL_APP / DATABASE_URL_APP_ADMIN)")


if __name__ == "__main__":
    asyncio.run(main())
