"""RLS for the five platform & visitor tables (docs/settings/rls-migration-proposal.md).

All five tables already exist (created by earlier migrations).  This migration
adds RLS policies to them.  None of the tables have a ``tenant_id`` column —
they are platform-level, not tenant-scoped — so all policies are GUC-gated
(readable when the tenant GUC is set) or per-user (via ``app.user_id``).

Tables and policies:

1. ``visitor_events`` (existing, no ``tenant_id``)
   — GUC-gated SELECT policy: readable only when the tenant GUC is set.
   The table owner (platform admin) bypasses RLS.

2. ``platform_announcements`` (existing, no ``tenant_id``)
   — read for every tenant session; write only by the platform admin (owner
   bypasses RLS because the table is **not** FORCE'd; the app role has no
   INSERT/UPDATE/DELETE policy and therefore cannot write at all).

3. ``platform_announcement_dismissals`` (existing, no ``tenant_id``, has ``user_id``)
   — per-user isolation via ``app.user_id`` GUC; FORCE'd so even the owner must
   bind the user GUC to read or write.

4. ``plan_prices`` (existing, no ``tenant_id``)
   — FORCE RLS with a GUC-gated SELECT policy (read when the tenant GUC is set,
   no writes from the app role).  Provision's ``sales_app_read`` is dropped;
   provision.py should stop re-creating it in a follow-up.

5. ``tax_rates`` (existing, no ``tenant_id``)
   — same shape as ``plan_prices``.

Idempotency: every statement is safe to run multiple times —
``ALTER TABLE … ENABLE/FORCE`` (no-ops if already set), and
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

_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    # --- 1. visitor_events: platform-level telemetry, no tenant_id ------------
    #       The table already exists (created by an earlier migration) with no
    #       tenant_id column — it is platform-level, not tenant-scoped.  RLS is
    #       GUC-gated: readable only when a tenant GUC is set (the app role never
    #       sees raw rows); the table owner (platform admin) bypasses RLS.
    op.execute("ALTER TABLE public.visitor_events ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.visitor_events")
    op.execute("DROP POLICY IF EXISTS visitor_events_read ON public.visitor_events")
    op.execute(
        """CREATE POLICY visitor_events_read ON public.visitor_events
            FOR SELECT
            USING (current_setting('app.tenant_id', true) IS NOT NULL)"""
    )

    # --- 2. platform_announcements: read for all, write for platform only -----
    #       NOT forced: the table owner (platform admin) bypasses RLS and can
    #       insert/update; the app role has only a SELECT policy.
    op.execute("ALTER TABLE public.platform_announcements ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS announcements_read ON public.platform_announcements")
    op.execute(
        "CREATE POLICY announcements_read ON public.platform_announcements FOR SELECT USING (true)"
    )

    # --- 3. platform_announcement_dismissals: per-user isolation -------------
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

    # --- 4. plan_prices: FORCE RLS, GUC-gated read ---------------------------
    op.execute("ALTER TABLE public.plan_prices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.plan_prices FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_app_read ON public.plan_prices")
    op.execute("DROP POLICY IF EXISTS plan_prices_read ON public.plan_prices")
    op.execute(
        """CREATE POLICY plan_prices_read ON public.plan_prices
            FOR SELECT
            USING (current_setting('app.tenant_id', true) IS NOT NULL)"""
    )

    # --- 5. tax_rates: FORCE RLS, GUC-gated read -----------------------------
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

    # Reverse policies on the tables (keep the tables themselves — they were
    # created by earlier migrations and have data/models we must not drop).
    op.execute(
        "DROP POLICY IF EXISTS dismissal_user_isolation ON public.platform_announcement_dismissals"
    )
    op.execute("ALTER TABLE public.platform_announcement_dismissals NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS announcements_read ON public.platform_announcements")

    op.execute("DROP POLICY IF EXISTS visitor_events_read ON public.visitor_events")
