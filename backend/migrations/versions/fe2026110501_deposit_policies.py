"""Deposit policies: the saved rule behind the deposit engine (Slice A).

Revision ID: fe2026110501
Revises: fe2026103001

The arithmetic half already exists (``app/modules/orders/deposit.py``) and is
session-free; this table is where a merchant's rule is kept. One row per
VERSION, with exactly one ``is_active`` row per tenant, so an order priced
against version 3 can still name the rule it was priced against after the
merchant edits it.

The "one active per tenant" rule lives in a PARTIAL UNIQUE INDEX rather than in
the service, because two concurrent saves are two transactions and a
check-then-insert pair would let both win.

No reservation- or payment-link-TTL column: the lifetime of a stock hold already
has exactly one owner, ``_RESERVATION_TTL`` in ``orders/service.py``, and a
second store of the same fact is a rule that can only drift from the first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026110501"
down_revision: str | None = "fe2026103001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# CI runs `alembic upgrade head` BEFORE scripts/provision.py creates the
# `sales_app` role, so a bare GRANT fails with UndefinedObjectError on a
# fresh database (the same reason f7a2c9d4e8b1 wraps its grants in a DO
# block). asyncpg allows exactly one statement per op.execute(), so each
# guarded grant is a single DO block.
_GRANT_SALES_APP = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {grant};
    END IF;
END
$$;"""


def _grant_sales_app(grant: str) -> str:
    return _GRANT_SALES_APP.format(grant=grant)


def upgrade() -> None:
    op.create_table(
        "deposit_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deposit_type", sa.String(length=31), nullable=False),
        sa.Column("deposit_value", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EGP", nullable=False),
        sa.Column(
            "calculation_base",
            sa.String(length=31),
            server_default="grand_total",
            nullable=False,
        ),
        sa.Column("minimum_deposit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("maximum_deposit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_deposit_policies_one_active_per_tenant",
        "deposit_policies",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_deposit_policies_tenant_active",
        "deposit_policies",
        ["tenant_id", "is_active"],
    )
    # Backstop for the concurrent-save race: max(version)+1 read by two
    # transactions must not be able to produce two rules under one version
    # number. save_policy also serialises per tenant with an advisory lock.
    op.create_unique_constraint(
        "uq_deposit_policies_tenant_version",
        "deposit_policies",
        ["tenant_id", "version"],
    )
    op.execute("ALTER TABLE deposit_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE deposit_policies FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON deposit_policies")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON deposit_policies
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        _grant_sales_app("GRANT SELECT, INSERT, UPDATE, DELETE ON deposit_policies TO sales_app")
    )


def downgrade() -> None:
    op.drop_table("deposit_policies")
