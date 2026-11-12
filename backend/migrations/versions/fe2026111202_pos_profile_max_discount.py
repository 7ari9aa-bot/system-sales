"""pos_profiles.max_discount_pct: the shop owner's own discount ceiling.

Revision ID: fe2026111202
Revises: fe2026111201
Create Date: 2026-11-12 14:00:00.000000

The owner decides how much a cashier may take off a sale; the platform does not pick a number for
them. NULL means no ceiling, which is what every existing profile has, so nothing about a shop that
never opens the setting changes and no backfill is needed.

SAFETY. Purely additive: one nullable column and a CHECK that a NULL always satisfies, so it holds
for every existing row. The column is added once, as every Alembic revision does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111202"
down_revision: str | None = "fe2026111201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Literal table and column names: tests/test_migrations.py reads them with an AST walk to prove
    # every model column is created by some migration.
    op.add_column("pos_profiles", sa.Column("max_discount_pct", sa.Numeric(5, 2), nullable=True))
    op.execute(
        "ALTER TABLE pos_profiles ADD CONSTRAINT ck_pos_profiles_max_discount_pct "
        "CHECK (max_discount_pct IS NULL OR (max_discount_pct >= 0 AND max_discount_pct <= 100))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE pos_profiles DROP CONSTRAINT IF EXISTS ck_pos_profiles_max_discount_pct"
    )
    op.drop_column("pos_profiles", "max_discount_pct")
