"""RLS for the five platform & visitor tables (docs/settings/rls-migration-proposal.md).

All five tables already exist (created by earlier migrations) and none of them
carry a ``tenant_id`` column — they are platform-level, not tenant-scoped — so
the standard ``tenant_isolation`` policy (which keys on ``tenant_id``) does not
apply.  Each gets a hand-written policy below.

Tables and policies (final design):

1. ``visitor_events`` (existing, no ``tenant_id``)
   — ENABLE RLS (NOT forced: the table owner / platform admin bypasses RLS
     and reads the cross-tenant telemetry analytics).
   — SELECT: readable by the app role only when a tenant GUC is bound
     (``NULLIF(...) IS NOT NULL`` — the plain ``IS NOT NULL`` test is weak:
     ``SET LOCAL`` leaves an empty string, not NULL, so the gate never closed).
   — INSERT: the public telemetry endpoint (``POST /public/telemetry``) writes
     without binding a tenant, and the table has no ``tenant_id`` to check, so
     the INSERT policy is ``WITH CHECK (true)``.  The GRANT (SELECT, INSERT
     from fe2026103001) is the first gate; RLS is the second.

2. ``platform_announcements`` (existing, no ``tenant_id``)
   — ENABLE RLS (NOT forced: the platform owner writes via the management API
     and bypasses RLS as the table owner).
   — SELECT for every session (``USING (true)``): announcements are global and
     every tenant reads the resolved subset.
   — No INSERT/UPDATE/DELETE policy: the app role (sales_app) cannot write.
     Platform writes go through the owner (RLS-exempt).

3. ``platform_announcement_dismissals`` (existing, no ``tenant_id``, has ``user_id``)
   — ENABLE + FORCE RLS: even the owner must bind the user GUC to read or write.
   — Per-user isolation via ``app.user_id`` GUC (``NULLIF`` guard): a user may
     only SELECT, INSERT (and DELETE where granted) their own dismissals.

4. ``plan_prices`` (existing, no ``tenant_id``)
   — ENABLE + FORCE RLS.
   — SELECT ``USING (true)``: a global catalog read by the public marketing
     page (``GET /public/markets/{country}``) with NO tenant GUC bound, so a
     GUC gate here would return zero rows and break the page.  Writes are
     blocked: no INSERT/UPDATE/DELETE policy, and provision.py REVOKEs
     INSERT/UPDATE/DELETE from sales_app (PRIVILEGE_REFREEZE).
   — The legacy ``sales_app_read`` policy (from provision.py's
     REFERENCE_PLANE_READ_POLICIES) is dropped here and NOT re-created by
     provision.py — ``plan_prices_read`` is the working replacement.

5. ``tax_rates`` (existing, no ``tenant_id``)
   — Same shape as ``plan_prices``.

Idempotency: every statement is safe to run multiple times —
``ALTER TABLE … ENABLE/FORCE`` (no-ops if already set), and
``DROP POLICY IF EXISTS`` before each ``CREATE POLICY``.

NOTE: ``provision.py`` no longer re-creates ``sales_app_read`` on
``plan_prices`` and ``tax_rates`` — this migration's policies supersede it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112602"
down_revision: str | None = "fe2026112601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL"
_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    # --- 1. visitor_events: platform telemetry, no tenant_id -----------------
    #       ENABLE (NOT forced): the owner / platform admin bypasses RLS to
    #       read cross-tenant analytics.  The app role (sales_app) gets:
    #         SELECT — only when a tenant GUC is bound (owner console, which
    #                  bind_tenant()s before reading).
    #         INSERT — always (the public telemetry endpoint has no tenant to
    #                  bind and the table has no tenant_id to check).
    op.execute("ALTER TABLE public.visitor_events ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.visitor_events")
    op.execute("DROP POLICY IF EXISTS visitor_events_read ON public.visitor_events")
    op.execute("DROP POLICY IF EXISTS visitor_events_insert ON public.visitor_events")
    op.execute(
        f"""CREATE POLICY visitor_events_read ON public.visitor_events
            FOR SELECT
            USING ({_TENANT_GUARD})"""
    )
    op.execute(
        """CREATE POLICY visitor_events_insert ON public.visitor_events
            FOR INSERT
            WITH CHECK (true)"""
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

    # --- 4. plan_prices: FORCE RLS, read for all, no writes ------------------
    #       USING (true) — NOT GUC-gated: the public marketing page reads
    #       plan_prices with no tenant GUC bound, so a GUC gate would break it.
    #       Writes are blocked by the absence of a write policy + the privilege
    #       REVOKE in provision.py.
    op.execute("ALTER TABLE public.plan_prices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.plan_prices FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_app_read ON public.plan_prices")
    op.execute("DROP POLICY IF EXISTS plan_prices_read ON public.plan_prices")
    op.execute(
        """CREATE POLICY plan_prices_read ON public.plan_prices
            FOR SELECT
            USING (true)"""
    )

    # --- 5. tax_rates: FORCE RLS, read for all, no writes --------------------
    op.execute("ALTER TABLE public.tax_rates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.tax_rates FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sales_app_read ON public.tax_rates")
    op.execute("DROP POLICY IF EXISTS tax_rates_read ON public.tax_rates")
    op.execute(
        """CREATE POLICY tax_rates_read ON public.tax_rates
            FOR SELECT
            USING (true)"""
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

    op.execute(
        "DROP POLICY IF EXISTS dismissal_user_isolation ON public.platform_announcement_dismissals"
    )
    op.execute("ALTER TABLE public.platform_announcement_dismissals NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS announcements_read ON public.platform_announcements")

    op.execute("DROP POLICY IF EXISTS visitor_events_insert ON public.visitor_events")
    op.execute("DROP POLICY IF EXISTS visitor_events_read ON public.visitor_events")
