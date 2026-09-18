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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.model_registry import Base  # noqa: E402

GUC = "app.tenant_id"
USER_GUC = "app.user_id"

FORCE_EXEMPT: set[str] = set()  # nothing exempt — FORCE applies to all tenant tables
NO_TENANT_TABLES = {
    "outbox_events",
    "idempotency_keys",
    "plans",
    "refresh_tokens",  # user-scoped, not tenant-scoped
}  # system/global
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
    # untouched; this is the only table with this variant.
    ula = "user_location_access"
    if ula in Base.metadata.tables:
        ula_user_guard = f"NULLIF(current_setting('{USER_GUC}', true), '')::uuid"
        stmts.append(f'ALTER TABLE public.{ula} ENABLE ROW LEVEL SECURITY;')
        stmts.append(f'ALTER TABLE public.{ula} FORCE ROW LEVEL SECURITY;')
        stmts.append(f'DROP POLICY IF EXISTS location_access ON public.{ula};')
        stmts.append(
            f'CREATE POLICY location_access ON public.{ula} '
            f'USING (user_id = {ula_user_guard}) '
            f'WITH CHECK (user_id = {ula_user_guard});'
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
    return stmts


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
    settings = get_settings()
    url = settings.database_url_admin or settings.database_url
    # asyncpg wants the plain postgres:// form without the +asyncpg suffix.
    dsn = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql.iixxqitfopsgvaheedlg", "postgres.iixxqitfopsgvaheedlg"
    )
    app_password = settings.sales_app_db_password or _random_password()
    conn = await asyncpg.connect(dsn, timeout=20)
    try:
        await setup_app_role(conn, app_password)
        statements = _rls_statements()
        for stmt in statements:
            await conn.execute(stmt)
        print(f"RLS applied: {len(statements)} statements")
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
