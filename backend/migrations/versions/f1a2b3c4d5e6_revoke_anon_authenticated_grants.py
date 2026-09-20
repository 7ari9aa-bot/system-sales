"""Revoke anon/authenticated privileges on public

CRITICAL (review G-01 / N-04). Supabase grants `anon` and `authenticated` full
DML on every table in `public` — SELECT, INSERT, UPDATE, DELETE, TRUNCATE,
REFERENCES, TRIGGER — and `pg_default_acl` grants the same on every *future*
table. `anon` is the key that ships in public client bundles, so it is not a
secret.

RLS happened to absorb most of this: 93 tables have `FORCE ROW LEVEL SECURITY`
with a `tenant_id = current_setting('app.tenant_id')` policy, which evaluates to
false for `anon` (no GUC set) and returns zero rows. The 12 tables WITHOUT RLS
have no such backstop, and they are the sensitive ones. Verified against
production with the public anon key before this migration:

    anon SELECT users           -> HTTP 206  rows=6    (emails, password hashes)
    anon SELECT refresh_tokens  -> HTTP 206  rows=30   (live session tokens)
    anon SELECT tenants         -> HTTP 206  rows=2
    anon SELECT customers       -> HTTP 200  rows=0    (RLS held)

`refresh_tokens` alone is account takeover for every user.

The application never uses PostgREST — the frontend calls the Railway API and
the backend connects directly as `sales_app` (which keeps its own grants, all
105 tables) — so revoking from anon/authenticated removes an attack surface
without removing any capability the product uses.

Revoking is the correct fix rather than adding RLS to those 12 tables: `users`,
`tenants` and `refresh_tokens` are global tables read during login, BEFORE any
tenant GUC is bound, so a tenant-scoped policy on them would break
authentication.

CI runs on plain Postgres where `anon`/`authenticated` do not exist, so every
statement is guarded on the role existing.
"""
from __future__ import annotations

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None

# Supabase's unauthenticated + end-user roles. `service_role` is deliberately
# NOT included: it is a server-side key with BYPASSRLS and Supabase tooling
# relies on it.
_ANON_ROLES = ("anon", "authenticated")

_REVOKE_EXISTING = """
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
        END IF;
    END LOOP;
END $$;
"""

# Applies to the role running the migration (postgres), so no membership in
# another role is required. Wrapped per-statement so a managed host that
# forbids ALTER DEFAULT PRIVILEGES cannot abort the whole migration.
_REVOKE_DEFAULTS = """
DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            BEGIN
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r
                );
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'default table privileges for % not changed', r;
            END;
            BEGIN
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r
                );
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'default sequence privileges for % not changed', r;
            END;
            BEGIN
                EXECUTE format(
                    'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I', r
                );
            EXCEPTION WHEN insufficient_privilege THEN
                RAISE NOTICE 'default function privileges for % not changed', r;
            END;
        END IF;
    END LOOP;
END $$;
"""


def upgrade() -> None:
    # NOTE: one statement per op.execute() — asyncpg's extended-query protocol
    # rejects multiple commands in a single execute().
    op.execute(_REVOKE_EXISTING)
    op.execute(_REVOKE_DEFAULTS)


def downgrade() -> None:
    """Deliberately does not restore the grants.

    Re-granting `anon` full DML on `users` and `refresh_tokens` would reinstate
    a credential-disclosure hole. Roll back the schema, not the security fix.
    """
    pass
