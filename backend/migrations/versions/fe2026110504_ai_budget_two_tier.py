"""Two-tier AI budget: a soft limit that warns and a hard stop that holds.

Revision ID: fe2026110504
Revises: fe2026110503

The §42 cap was single-tier: at 100% the block policy raised on every
reservation and the only way out was editing the number. The merchant contract
is now two limits:

- ``soft_cap`` — crossing it sends the tenant's owners a renewal-asking
  notification; usage continues. ``NULL`` means "no soft tier" and preserves
  the old behaviour exactly.
- ``hard_stopped_at`` — a DURABLE stop state, not a re-derived comparison.
  When the hard cap is crossed under ``on_exceed = block`` the policy row is
  stamped; from then on every reservation is refused even if spend somehow
  reads below the cap. A state beats a recomputation here because the two
  readers (the reservation path and the owner console) must agree on "is this
  tenant stopped" without re-deriving spend twice.
- ``hard_stop_lifted_period`` — the "YYYY-MM" in which the stop was last
  lifted (auto on reactivation or manually from the console). A lift is only
  honoured for the REST of that period: the stop can be re-applied next
  month, so a renewal mid-month does not flip-flop stop/lift/stop within the
  same period.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026110504"
down_revision: str | None = "fe2026110503"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_budget_policies",
        sa.Column(
            "soft_cap",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_budget_policies",
        sa.Column("hard_stopped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_budget_policies",
        sa.Column("hard_stop_lifted_period", sa.String(length=7), nullable=True),
    )
    op.create_check_constraint(
        "ck_ai_budget_soft_below_hard",
        "ai_budget_policies",
        "soft_cap IS NULL OR hard_cap <= 0 OR soft_cap <= hard_cap",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_budget_soft_below_hard", "ai_budget_policies", type_="check")
    op.drop_column("ai_budget_policies", "hard_stop_lifted_period")
    op.drop_column("ai_budget_policies", "hard_stopped_at")
    op.drop_column("ai_budget_policies", "soft_cap")
