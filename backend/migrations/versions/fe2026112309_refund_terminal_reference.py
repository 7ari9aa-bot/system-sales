"""refunds carry the terminal's reference for a card/wallet reversal

Revision ID: fe2026112309
Revises: fe2026112308
Create Date: 2026-11-24 03:40:00.000000

The till recorded a card/wallet refund as ``processed`` the moment it wrote the row, but the
reversal itself happens on the shop's terminal: nothing in this database could prove it happened.
``external_reference`` is that proof - the RRN, approval code or transfer number the cashier reads
off the terminal - and a non-cash refund stays ``pending`` until it is filled in.

Nullable with no backfill: every existing row predates the rule and is already ``processed``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112309"
down_revision: str | None = "fe2026112308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refunds",
        sa.Column("external_reference", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refunds", "external_reference")
