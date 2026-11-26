"""A branch keeps its own week.

Revision ID: fe2026112613
Revises: fe2026112612

The settings map gives Locations a "Branch hours" page, and the schema had nowhere
to put it: ``locations`` carried a name, a code and an active flag, while the only
hours in the system were the store's published prose in ``knowledge_items`` — the
text the customer agent quotes when someone asks "when are you open". That prose is
the store's promise; it cannot answer for a second branch that opens later or closes
on Friday.

Deliberate modelling decisions:

- ``hours`` is a JSONB column on the branch itself, not a settings key. Hours are
  facts about one branch (the shape differs per day and per branch), not a policy
  the settings engine resolves. A key would have had to hold a free-form blob and
  the engine's inheritance would mean nothing for it.
- NULL means "follows the store". That is the state every existing row starts in and
  the state a single-branch shop should stay in, so the column is nullable and no
  backfill is needed. An empty object is normalised to NULL by the service, which
  keeps one representation of the same intent.
- No new grant: ``locations`` is already granted to ``sales_app``, and a column
  addition needs no GRANT of its own.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112613"
down_revision: str | None = "fe2026112612"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column("hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("locations", "hours")
