"""pos: per-profile money ceilings for a return and for cash leaving the drawer.

Revision ID: fe2026102105
Revises: fe2026102104
Create Date: 2026-10-21 09:30:00.000000

Until now only a discount had a ceiling. A return or a cash pay-out of any size needed nothing but
the cashier's own session. These two columns let the shop owner set how much a cashier may move
alone; above it the action needs a manager's approval (the same PIN as a discount).

Both are NULL by default = no limit, so no existing shop changes behaviour until its owner sets one.
Plain columns on an existing tenant-scoped table: its RLS policy already covers them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102105"
down_revision: str | None = "fe2026102104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pos_profiles", sa.Column("refund_ceiling", sa.Numeric(14, 2), nullable=True))
    op.add_column("pos_profiles", sa.Column("cash_out_ceiling", sa.Numeric(14, 2), nullable=True))
    op.create_check_constraint(
        "ck_pos_profiles_refund_ceiling_nonneg",
        "pos_profiles",
        "refund_ceiling IS NULL OR refund_ceiling >= 0",
    )
    op.create_check_constraint(
        "ck_pos_profiles_cash_out_ceiling_nonneg",
        "pos_profiles",
        "cash_out_ceiling IS NULL OR cash_out_ceiling >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pos_profiles_cash_out_ceiling_nonneg", "pos_profiles", type_="check")
    op.drop_constraint("ck_pos_profiles_refund_ceiling_nonneg", "pos_profiles", type_="check")
    op.drop_column("pos_profiles", "cash_out_ceiling")
    op.drop_column("pos_profiles", "refund_ceiling")
