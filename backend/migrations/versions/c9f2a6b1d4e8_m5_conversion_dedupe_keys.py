"""M5 — dedupe keys for conversions and attribution credits.

``MarketingService.record_conversion`` had no uniqueness behind it, so a replayed
order event booked the same order twice and every figure that divides by
conversions (ROAS, conversion rate, credited revenue) rose with it. A
SELECT-then-INSERT guard cannot fix that: two concurrent retries both read "no
row" and both write. The database is the only place the guarantee holds.

The same applies one level down. Attribution rows carry a ``model`` precisely so
first-touch and last-touch can be two *views* of one order, but nothing stopped a
second row crediting the same touchpoint twice under the same model — which is
not a second view, it is twice the money.

Both keys are non-partial on purpose: ``conversions.order_id`` is NULL for
anonymous conversions, and Postgres compares NULLs as distinct in a unique index,
so those keep their multiplicity.

Revision ID: c9f2a6b1d4e8
Revises: b8e1c4d5a7f2
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9f2a6b1d4e8"
down_revision: str | None = "b8e1c4d5a7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Collapse pre-existing duplicate credits first, or the constraint below
    # aborts the deploy on the first database that already has them.
    op.execute(
        "DELETE FROM attributions a USING attributions b "
        "WHERE a.id < b.id AND a.tenant_id = b.tenant_id "
        "AND a.conversion_id = b.conversion_id AND a.model = b.model "
        "AND a.touchpoint_id = b.touchpoint_id"
    )
    # Likewise for conversions: keep the earliest row per (tenant, order, type).
    op.execute(
        "DELETE FROM conversions a USING conversions b "
        "WHERE a.id < b.id AND a.tenant_id = b.tenant_id AND a.type = b.type "
        "AND a.order_id IS NOT NULL AND a.order_id = b.order_id"
    )
    op.create_unique_constraint(
        "uq_conversions_tenant_order_type",
        "conversions",
        ["tenant_id", "order_id", "type"],
    )
    op.create_unique_constraint(
        "uq_attributions_credit",
        "attributions",
        ["tenant_id", "conversion_id", "model", "touchpoint_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_attributions_credit", "attributions", type_="unique")
    op.drop_constraint("uq_conversions_tenant_order_type", "conversions", type_="unique")
