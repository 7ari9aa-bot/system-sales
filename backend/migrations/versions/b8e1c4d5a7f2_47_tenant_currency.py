"""§47 — a tenant declares the currency it trades in.

Every money column in this schema is ``NUMERIC(14,2)`` and every value written
to it is a ``Decimal``, so "not floating point money" was already true. What was
NOT true is the other half of §47: the currency was a Python literal. Five model
columns carried ``server_default="EGP"``, and the service paths that name a
currency at all — checkout, ``add_payment``, a billing invoice, a marketing
conversion, the customer money card — each wrote their own copy of that literal.
A tenant could therefore hold a price tier in USD next to an invoice in EGP, and
nothing anywhere could tell which of the two the customer actually owed.

One currency per tenant, on the tenant's own row, is what turns a mixed currency
into a refusal instead of a conversion. That is why this migration adds a column
and no FX table: §47 forbids rewriting the original amount, and with a single
trading currency there is never a reason to.

``server_default`` backfills the existing rows with EGP — the value the code was
already writing — so the column cannot be born lying about the orders already in
the database.

Revision ID: b8e1c4d5a7f2
Revises: a7d0f4b2c6e9
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e1c4d5a7f2"
down_revision: str | None = "a7d0f4b2c6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EGP"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "currency")
