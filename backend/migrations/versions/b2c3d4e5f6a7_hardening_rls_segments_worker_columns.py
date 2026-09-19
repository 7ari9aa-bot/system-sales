"""hardening: segments table, RLS in migrations, scheduler/worker columns

Revision ID: b2c3d4e5f6a7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-19

Closes verified gaps from docs/GAP_REGISTER.md:
- C11/O2: segments table was never created (empty migration + unregistered model).
- C12: RLS lived only in scripts/provision.py — a migrated-but-unprovisioned
  database had zero tenant isolation. The DDL now lives HERE; provision.py
  remains idempotent (same policy names) for grants/seed/verification.
- C8: agent_runs.status widened to 31 chars ("WAITING_APPROVAL" is 16).
- C9: conversations gains a partial unique index so two concurrent ingests can
  never open duplicate conversations for the same customer/channel.
- R2: outbox_events.not_before enables durable (DB-backed) retry scheduling.

RLS exemptions (system plumbing, no tenant rows read cross-tenant by design):
outbox_events, idempotency_keys, plans, refresh_tokens, webhook_events,
scheduled_jobs (the scheduler claims due jobs across tenants before any
tenant context exists — §125 tenant enumeration is a later milestone).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables with a tenant_id column that must NOT get the standard policy.
_RLS_EXEMPT = (
    "outbox_events",
    "idempotency_keys",
    "plans",
    "refresh_tokens",
    "webhook_events",
    "scheduled_jobs",
    # special-cased below with their own policies:
    "audit_logs",
    "security_events",
)

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# Channel webhooks arrive BEFORE any tenant is known, so tenant resolution
# cannot read `integrations` directly — that table is FORCE-RLS and the GUC is
# not bound yet, so a plain SELECT returns zero rows and every inbound webhook
# is acknowledged while ingesting nothing. SECURITY DEFINER runs the lookup as
# the table owner (which bypasses RLS) and returns ONLY the tenant id, so the
# provider credentials in integrations.config never leave the table.
# search_path is pinned — mandatory for SECURITY DEFINER.
# Kept byte-identical to CHANNEL_TENANT_FN_SQL in scripts/provision.py (they
# run in either order; a divergence would make the result order-dependent).
_CHANNEL_TENANT_FN = """
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
       -- 'active' is the §145 lifecycle value; 'connected' is the legacy
       -- value still present on databases that predate the backfill.
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

# NOTE: one statement per op.execute(). Migrations run through asyncpg, whose
# extended-query protocol rejects multiple commands in a single execute
# ("cannot insert multiple commands into a prepared statement"), so the
# function body and its REVOKE must be issued separately.
_CHANNEL_TENANT_FN_REVOKE = (
    "REVOKE ALL ON FUNCTION public.resolve_channel_tenant(text, text) FROM PUBLIC;"
)

# tenant_users carries a tenant_id but is ALSO how a user's memberships are
# discovered at login — before any tenant context exists. The generic policy
# (tenant_id = app.tenant_id) would hide every row at that moment and break
# sign-in entirely, so it keeps the user-guard variant (mirrors provision.py).
_USER_GUARDED = ("tenant_users",)


def _segments_table() -> None:
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_segments_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_segments_tenant_name", "segments", ["tenant_id", "name"], unique=False
    )


def _rls_do_block() -> None:
    """Apply the standard tenant_isolation policy to every tenant table.

    Dynamic over information_schema so future tables are covered by re-running
    provision.py or re-basing this block — the policy NAME stays stable.
    """
    exempt = ", ".join(f"'{t}'" for t in _RLS_EXEMPT)
    user_guarded = ", ".join(f"'{t}'" for t in _USER_GUARDED)
    op.execute(
        f"""
        DO $$
        DECLARE
            r record;
            -- The guards are DOLLAR-QUOTED and passed to format() as %s
            -- ARGUMENTS, never spliced into the format string. Splicing them
            -- put a raw single quote inside a single-quoted literal
            -- (current_setting('app.tenant_id'...) inside 'CREATE POLICY ...'),
            -- so the whole DO block failed to parse and `alembic upgrade head`
            -- aborted with `syntax error at or near "app"`.
            tenant_guard text := $g${_TENANT_GUARD}$g$;
            user_guard text := $g${_USER_GUARD}$g$;
        BEGIN
            FOR r IN
                SELECT DISTINCT c.table_name
                FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_name = c.table_name AND t.table_schema = 'public'
                WHERE c.table_schema = 'public'
                  AND c.column_name = 'tenant_id'
                  AND c.table_name NOT IN ({exempt})
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.table_name);
                EXECUTE format(
                    'ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', r.table_name);
                EXECUTE format(
                    'DROP POLICY IF EXISTS tenant_isolation ON public.%I', r.table_name);
                EXECUTE format(
                    'DROP POLICY IF EXISTS notifications_tenant_isolation ON public.%I',
                    r.table_name);
                IF r.table_name = ANY (ARRAY[{user_guarded}]) THEN
                    EXECUTE format(
                        'CREATE POLICY tenant_isolation ON public.%I '
                        'USING (tenant_id = %s OR user_id = %s) '
                        'WITH CHECK (tenant_id = %s OR user_id = %s)',
                        r.table_name, tenant_guard, user_guard, tenant_guard, user_guard);
                ELSE
                    EXECUTE format(
                        'CREATE POLICY tenant_isolation ON public.%I '
                        'USING (tenant_id = %s) WITH CHECK (tenant_id = %s)',
                        r.table_name, tenant_guard, tenant_guard);
                END IF;
            END LOOP;
        END $$;
        """
    )

    # audit_logs: platform actions write NULL-tenant rows — ENABLE but NO FORCE,
    # policy allows NULL or matching tenant (mirrors provision.py).
    op.execute("ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.audit_logs NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.audit_logs")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.audit_logs
            USING (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})"""
    )

    # security_events: pre-auth rows carry NULL tenant (login failures) — the
    # previous strict policy silently rejected them under RLS.
    op.execute("ALTER TABLE public.security_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.security_events FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.security_events")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.security_events
            USING (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id IS NULL OR tenant_id = {_TENANT_GUARD})"""
    )

    # customer_tags: no tenant_id column — tenancy resolves via the parent row.
    op.execute("ALTER TABLE public.customer_tags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.customer_tags FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.customer_tags")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.customer_tags
            USING (EXISTS (
                SELECT 1 FROM public.customers p
                WHERE p.id = customer_tags.customer_id AND p.tenant_id = {_TENANT_GUARD}))
            WITH CHECK (EXISTS (
                SELECT 1 FROM public.customers p
                WHERE p.id = customer_tags.customer_id AND p.tenant_id = {_TENANT_GUARD}))"""
    )

    # user_location_access: user-keyed grant table.
    op.execute("ALTER TABLE public.user_location_access ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.user_location_access FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS location_access ON public.user_location_access")
    op.execute(
        f"""CREATE POLICY location_access ON public.user_location_access
            USING (user_id = {_USER_GUARD})
            WITH CHECK (user_id = {_USER_GUARD})"""
    )


def upgrade() -> None:
    _segments_table()

    # agent_runs.status: "WAITING_APPROVAL" (16 chars) overflowed varchar(15).
    op.alter_column("agent_runs", "status", type_=sa.String(length=31))

    # Durable retry scheduling for the outbox relay (workers ack an event and
    # stage a retry with not_before instead of sleeping in-process).
    op.add_column(
        "outbox_events",
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
    )

    # At most one open conversation per (tenant, customer, channel).
    op.create_index(
        "uq_conversations_open_tenant_customer_channel",
        "conversations",
        ["tenant_id", "customer_id", "channel"],
        unique=True,
        postgresql_where=sa.text("status <> 'closed'"),
    )

    # S10: webhook ingress replay guard. Both providers sign a STATIC HMAC over
    # the raw body (no timestamp/nonce in their contract), so an intercepted
    # delivery can be replayed verbatim. The ingress row now carries a digest
    # of the raw body in external_event_id and this UNIQUE index turns a replay
    # into a no-op instead of a duplicate write. Postgres treats NULLs as
    # distinct, so legacy rows without a digest are unaffected.
    #
    # The model declares a NON-unique ix_webhook_events_provider_ext, so
    # ON CONFLICT (provider, external_event_id) in the router has nothing to
    # match unless THIS index exists — without it every webhook raised
    # InvalidColumnReference and inbound messaging 500'd.
    op.create_index(
        "uq_webhook_events_provider_external",
        "webhook_events",
        ["provider", "external_event_id"],
        unique=True,
    )

    _rls_do_block()

    op.execute(_CHANNEL_TENANT_FN)
    op.execute(_CHANNEL_TENANT_FN_REVOKE)
    # sales_app is created by scripts/provision.py, which may run either before
    # or after migrations — grant only when the role is already present.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.resolve_channel_tenant(text, text)
                    TO sales_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.resolve_channel_tenant(text, text)")
    op.drop_index("uq_webhook_events_provider_external", table_name="webhook_events")
    op.drop_index(
        "uq_conversations_open_tenant_customer_channel", table_name="conversations"
    )
    op.drop_column("outbox_events", "not_before")
    op.alter_column("agent_runs", "status", type_=sa.String(length=15))
    op.drop_index("ix_segments_tenant_name", table_name="segments")
    op.drop_table("segments")
    # RLS policies are intentionally NOT dropped on downgrade: disabling
    # tenant isolation is never a rollback path anyone should want.
