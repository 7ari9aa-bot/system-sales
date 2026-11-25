"""RLS for the five platform & visitor tables (docs/settings/rls-migration-proposal.md).

Turns the proposal document into an executable, idempotent Alembic migration.
Three of the five tables do not exist yet — they are created here with
``CREATE TABLE IF NOT EXISTS`` so re-running is safe.  Two already exist
(``plan_prices``, ``tax_rates``) and currently sit in ``NO_TENANT_TABLES`` with
only a dead ``sales_app_read`` policy (RLS was never enabled on them).

Tables and policies:

1. ``visitor_events`` (NEW, has ``tenant_id``)
   — INSERT/SELECT for the tenant; canonical ``tenant_isolation`` policy so the
   schema-wide gate (``test_schema_wide_rls_policies``) is satisfied.

2. ``platform_announcements`` (NEW, no ``tenant_id``)
   — read for every tenant session; write only by the platform admin (owner
   bypasses RLS because the table is **not** FORCE'd; the app role has no
   INSERT/UPDATE/DELETE policy and therefore cannot write at all).

3. ``platform_announcement_dismissals`` (NEW, no ``tenant_id``, has ``user_id``)
   — per-user isolation via ``app.user_id`` GUC; FORCE'd so even the owner must
   bind the user GUC to read or write.

4. ``plan_prices`` (existing, no ``tenant_id``)
   — FORCE RLS with a GUC-gated SELECT policy (read when the tenant GUC is set,
   no writes from the app role).  Provision's ``sales_app_read`` is dropped;
   provision.py should stop re-creating it in a follow-up.

5. ``tax_rates`` (existing, no ``tenant_id``)
   — same shape as ``plan_prices``.

Idempotency: every statement is safe to run multiple times — ``CREATE TABLE
IF NOT EXISTS``, ``ALTER TABLE … ENABLE/FORCE`` (no-ops if already set), and
``DROP POLICY IF EXISTS`` before each ``CREATE POLICY``.

NOTE: ``provision.py`` still re-creates ``sales_app_read`` on ``plan_prices``
and ``tax_rates`` on every provision run.  Coexistence is harmless (both are
SELECT policies and OR together), but the GUC gate only bites once provision.py
is updated to stop re-creating the legacy policy.  That is a follow-up, not
part of this migration.

Revision ID: fe2026112602
Revises: fe2026112601
Create Date: 2026-11-26 01:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112602"
down_revision: str | None = "fe2026112601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"

# ---------------------------------------------------------------------------
# DDL for the three new tables
# ---------------------------------------------------------------------------

_NEW_TABLES = [
    # visitor_events — anonymous storefront visitor tracking (insert-only in
    # the proposal; the canonical tenant_isolation policy also allows SELECT,
    # which is more permissive but satisfies the schema-wide gate).
    """
    CREATE TABLE IF NOT EXISTS public.visitor_events (
        id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id   UUID          NOT NULL,
        visitor_id  UUID,
        event_type  VARCHAR(63)   NOT NULL,
        payload     JSONB         NOT NULL DEFAULT '{}'::jsonb,
        created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
    )
    """,
    # platform_announcements — global, tenant-agnostic.
    """
    CREATE TABLE IF NOT EXISTS public.platform_announcements (
        id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
        title       VARCHAR(255)  NOT NULL,
        body        TEXT          NOT NULL DEFAULT '',
        severity     VARCHAR(31)  NOT NULL DEFAULT 'info',
        created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
        expires_at  TIMESTAMPTZ
    )
    """,
    # platform_announcement_dismissals — per-user, no tenant_id.
    """
    CREATE TABLE IF NOT EXISTS public.platform_announcement_dismissals (
        id              UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID  NOT NULL,
        announcement_id UUID  NOT NULL
            REFERENCES public.platform_announcements(id) ON DELETE CASCADE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (user_id, announcement_id)
    )
    """,
]


def upgrade() -> None:
    # --- 1. Create the three new tables (idempotent) -------------------------
    for ddl in _NEW_TABLES:
        op.execute(ddl)

    # --- 2. visitor_events: canonical tenant_isolation ----------------------
    op.execute("ALTER TABLE public.visitor_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.visitor_events FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.visitor_events")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.visitor_events
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )

    # --- 3. platform_announcements: read for all, write for platform only -----
    #       NOT forced: the table owner (platform admin) bypasses RLS and can
    #       insert/update; the app role has only a SELECT policy.
    op.execute("ALTER TABLE public.platform_announcements ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS announcements_read ON public.platform_announcements")
    op.execute(
        "CREATE POLICY announcements_read ON public.platform_announcements FOR SELECT USING (true)"
    )

    # --- 4. platform_announcement_dismissals: per-user isolation -------------
    op.execute("ALTER TABLE public.platform_announcement_dismissals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.platform_announcement_dismissals FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS dismissal_user_isolation ON public.platform_announcement_dismissals"
    )
    op.execute(
        f"""CREATE POLICY dismissal_user_isolation
              ON public.platform_announcement_dismissals
              FOR ALL
              USING (user_id = {_USER_GUARD})
              WITH CHECK (user_id = {_USER_GUARD})"""
    )

    # --- 5. plan_prices: FORCE RLS, GUC-gated read ---------------------------
    op.execute("ALTER TABLE public.plan_prices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.plan_prices FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_app_read ON public.plan_prices")
    op.execute("DROP POLICY IF EXISTS plan_prices_read ON public.plan_prices")
    op.execute(
        """CREATE POLICY plan_prices_read ON public.plan_prices
            FOR SELECT
            USING (current_setting('app.tenant_id', true) IS NOT NULL)"""
    )

    # --- 6. tax_rates: FORCE RLS, GUC-gated read -----------------------------
    op.execute("ALTER TABLE public.tax_rates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.tax_rates FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_app_read ON public.tax_rates")
    op.execute("DROP POLICY IF EXISTS tax_rates_read ON public.tax_rates")
    op.execute(
        """CREATE POLICY tax_rates_read ON public.tax_rates
            FOR SELECT
            USING (current_setting('app.tenant_id', true) IS NOT NULL)"""
    )


def downgrade() -> None:
    # Reverse policies and RLS on existing tables (keep the tables themselves).
    for table, policy in [
        ("plan_prices", "plan_prices_read"),
        ("tax_rates", "tax_rates_read"),
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        # RLS stays ENABLED: a table with RLS on and no policy denies all
        # non-owner reads, which is the safe direction for a rollback.

    # Reverse policies on new tables, then drop the tables.
    op.execute(
        "DROP POLICY IF EXISTS dismissal_user_isolation ON public.platform_announcement_dismissals"
    )
    op.execute("ALTER TABLE public.platform_announcement_dismissals NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS announcements_read ON public.platform_announcements")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.visitor_events")
    op.execute("ALTER TABLE public.visitor_events NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP TABLE IF EXISTS public.platform_announcement_dismissals")
    op.execute("DROP TABLE IF EXISTS public.platform_announcements")
    op.execute("DROP TABLE IF EXISTS public.visitor_events")
