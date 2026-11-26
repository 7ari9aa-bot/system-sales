"""merge the pricing/offers line with the w7a wiring line

Revision ID: fe2026112615
Revises: fe2026112614, f8a1c2d3e4b5
Create Date: 2026-11-26

The branch that built sections 18-20 also merged main, which had added f8a1c2d3e4b5 on its own
line. Both lines live in this tree, so the graph had two heads and `alembic upgrade head` aborted
before applying a single change ("Multiple head revisions are present") — the first step of every
deploy, and every backend test shard.

Neither line has to be rewritten: this revision only joins them. A database already at
f8a1c2d3e4b5 (production, and every environment deployed from main) gets the pricing and offers
migrations and then lands here; a fresh database runs both lines and joins them the same way.
"""

from collections.abc import Sequence

revision: str = "fe2026112615"
down_revision: tuple[str, str] = ("fe2026112614", "f8a1c2d3e4b5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change: the two lines are independent and both already applied."""


def downgrade() -> None:
    """No schema change: splitting the heads again would abort the next upgrade."""
