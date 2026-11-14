"""tenants.dialect: the Arabic dialect the shop owner wants the assistant to use.

Revision ID: fe2026111209
Revises: fe2026111208
Create Date: 2026-11-14 01:10:00.000000

The owner's assistant answers in a dialect, and which one is the shop owner's call. A shop has a
currency and a timezone but no country, so the dialect is its own explicit setting.

NULL is a meaningful value, not a gap: it says "the owner never chose", and the assistant then
derives the dialect from the shop's currency when it answers. So there is NO backfill and NO server
default: choosing a dialect for a live shop would be inventing a choice the owner never made.

The CHECK is a closed list. Unlike the timezone (whose valid names live in tzdata, which PostgreSQL
does not have), this list is five fixed keys, so the database can enforce it outright and a stray
write that skips the service still cannot store a value the code does not know. The keys mirror
``identity.dialects.CHOICES``; a test keeps the two from drifting.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111209"
down_revision: str | None = "fe2026111208"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIALECT_CHECK = "dialect IS NULL OR dialect IN ('egyptian', 'gulf', 'levantine', 'maghrebi', 'msa')"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("dialect", sa.String(length=16), nullable=True))
    op.create_check_constraint("tenants_dialect_listed", "tenants", _DIALECT_CHECK)


def downgrade() -> None:
    op.drop_constraint("tenants_dialect_listed", "tenants", type_="check")
    op.drop_column("tenants", "dialect")
