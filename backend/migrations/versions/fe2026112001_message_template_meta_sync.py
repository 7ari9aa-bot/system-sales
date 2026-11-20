"""Message templates keep what Meta needs to review them, and why it said no.

Revision ID: fe2026112001
Revises: fe2026111901
Create Date: 2026-11-20 02:30:00.000000

WHY. A WhatsApp template only exists for Meta once it is created on the business account and
reviewed there, and the table held just a name and a body. Three columns, all additive:

* ``category``  - UTILITY / MARKETING / AUTHENTICATION. Meta prices and limits each differently, and
  it cannot be left out of the request. NULL for templates of other channels.
* ``components`` - the header / footer / buttons exactly as they are sent to Meta, so one column
  carries every shape of template (and the ones Meta adds later) without another migration.
* ``rejection_reason`` - Meta's own words, shown to the owner so they can fix the text.

Nothing is backfilled: an existing row keeps working as before (``components`` defaults to an empty
list, which means "just the body").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112001"
down_revision: str | None = "fe2026111901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("message_templates", sa.Column("category", sa.String(length=15), nullable=True))
    op.add_column(
        "message_templates",
        sa.Column(
            "components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("message_templates", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("message_templates", "rejection_reason")
    op.drop_column("message_templates", "components")
    op.drop_column("message_templates", "category")
