"""V12 Wave B — Authority Plane: capability_grants, authority_leases,
autonomy_budgets, budget_reservations

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-09-27

Four tenant-scoped tables implementing V12 §20–§25:

1. ``capability_grants``     — durable grants bounding action scope and budget.
2. ``authority_leases``      — ephemeral single-use tokens with command_hash
                               binding, nonce uniqueness, and TTL <= 60s.
3. ``autonomy_budgets``      — parent-sliced budget hierarchy for agents.
4. ``budget_reservations``   — in-flight holds while leases are active.

RLS: all four get ENABLE + FORCE + ``tenant_isolation`` policy via the
standard ``app.tenant_id`` GUC through the NULLIF guard.
One statement per ``op.execute()`` — asyncpg requirement.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d2b3c4e5f6a7"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE + the standard tenant_isolation policy for one table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.{table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    # 1. capability_grants
    op.create_table(
        "capability_grants",
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=31), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("max_budget", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "currency", sa.String(length=15),
            server_default="USD", nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=31),
            server_default="ACTIVE", nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("grant_id"),
    )
    op.create_index("ix_capability_grants_tenant_tool", "capability_grants", ["tenant_id", "tool_name"])
    op.create_index("ix_capability_grants_tenant_status", "capability_grants", ["tenant_id", "status"])
    op.create_index("ix_capability_grants_decision", "capability_grants", ["decision_id"])
    _enable_rls("capability_grants")

    # 2. authority_leases
    op.create_table(
        "authority_leases",
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), unique=True, nullable=False),
        sa.Column("command_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "expected_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column(
            "state", sa.String(length=31),
            server_default="MINTED", nullable=False,
        ),
        sa.Column(
            "ttl_seconds", sa.Integer(),
            server_default="60", nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reserved_budget", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("lease_id"),
    )
    op.create_index("ix_authority_leases_tenant_state", "authority_leases", ["tenant_id", "state"])
    op.create_index("ix_authority_leases_tenant_decision", "authority_leases", ["tenant_id", "decision_id"])
    op.create_index("ix_authority_leases_token_hash", "authority_leases", ["lease_token_hash"])
    op.create_index("ix_authority_leases_tenant_nonce", "authority_leases", ["tenant_id", "nonce"], unique=True)
    _enable_rls("authority_leases")

    # 3. autonomy_budgets
    op.create_table(
        "autonomy_budgets",
        sa.Column("budget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_budget_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column(
            "period", sa.String(length=31),
            server_default="DAILY", nullable=False,
        ),
        sa.Column(
            "currency", sa.String(length=15),
            server_default="USD", nullable=False,
        ),
        sa.Column("total_limit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "spent_amount", sa.Numeric(precision=14, scale=2),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "reserved_amount", sa.Numeric(precision=14, scale=2),
            server_default="0", nullable=False,
        ),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("budget_id"),
    )
    op.create_index("ix_autonomy_budgets_tenant", "autonomy_budgets", ["tenant_id"])
    op.create_index("ix_autonomy_budgets_parent", "autonomy_budgets", ["parent_budget_id"])
    _enable_rls("autonomy_budgets")

    # 4. budget_reservations
    op.create_table(
        "budget_reservations",
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("budget_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status", sa.String(length=31),
            server_default="RESERVED", nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("reservation_id"),
    )
    op.create_index("ix_budget_reservations_tenant_budget", "budget_reservations", ["tenant_id", "budget_id"])
    op.create_index("ix_budget_reservations_lease", "budget_reservations", ["lease_id"])
    _enable_rls("budget_reservations")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.budget_reservations")
    op.drop_index("ix_budget_reservations_lease", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_tenant_budget", table_name="budget_reservations")
    op.drop_table("budget_reservations")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.autonomy_budgets")
    op.drop_index("ix_autonomy_budgets_parent", table_name="autonomy_budgets")
    op.drop_index("ix_autonomy_budgets_tenant", table_name="autonomy_budgets")
    op.drop_table("autonomy_budgets")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.authority_leases")
    op.drop_index("ix_authority_leases_tenant_nonce", table_name="authority_leases")
    op.drop_index("ix_authority_leases_token_hash", table_name="authority_leases")
    op.drop_index("ix_authority_leases_tenant_decision", table_name="authority_leases")
    op.drop_index("ix_authority_leases_tenant_state", table_name="authority_leases")
    op.drop_table("authority_leases")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.capability_grants")
    op.drop_index("ix_capability_grants_decision", table_name="capability_grants")
    op.drop_index("ix_capability_grants_tenant_status", table_name="capability_grants")
    op.drop_index("ix_capability_grants_tenant_tool", table_name="capability_grants")
    op.drop_table("capability_grants")
