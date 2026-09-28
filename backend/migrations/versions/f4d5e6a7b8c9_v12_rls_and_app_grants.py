"""Repair V12 RLS policy mode and grant runtime table access.

Revision ID: f4d5e6a7b8c9
Revises: e3c4d5f6a7b8
Create Date: 2026-09-28

The Wave C migration created only a RESTRICTIVE tenant policy on its four new
tables. PostgreSQL needs at least one PERMISSIVE policy or RLS denies every
row. Also grant the non-bypassrls runtime role DML on the V12 tables; the
provision script's default privileges do not apply retroactively.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4d5e6a7b8c9"
down_revision: str | None = "e3c4d5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_WAVE_C_TABLES = (
    "effect_ledger",
    "chart_of_accounts",
    "financial_transactions",
    "financial_entries",
)
def upgrade() -> None:
    for table in _WAVE_C_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )

    # CI provisions sales_app after Alembic, while production already has it.
    # Guard the grants so both deploy orders remain valid.
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              public.decisions, public.evidence_facts, public.evidence_sets,
              public.decision_dependencies, public.capability_grants,
              public.authority_leases, public.autonomy_budgets,
              public.budget_reservations, public.effect_ledger,
              public.chart_of_accounts, public.financial_transactions,
              public.financial_entries TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE
              public.decisions, public.evidence_facts, public.evidence_sets,
              public.decision_dependencies, public.capability_grants,
              public.authority_leases, public.autonomy_budgets,
              public.budget_reservations, public.effect_ledger,
              public.chart_of_accounts, public.financial_transactions,
              public.financial_entries FROM sales_app;
          END IF;
        END
        $$"""
    )
    for table in _WAVE_C_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON public.{table}
                AS RESTRICTIVE
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )
