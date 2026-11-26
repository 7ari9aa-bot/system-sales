"""join the pricing/offers line with main's invitation-token line

Revision ID: fe2026112615
Revises: fe2026112614, fe2026112609
Create Date: 2026-11-26

Two lines were live at once and `alembic upgrade head` refuses more than one head: this branch's
pricing and offers work, and main's invitation-token migration (fe2026112609, added by d720c255
while this branch was open). Main was already broken on its own by then — fe2026112609 chains onto
fe2026112608, which is not an ancestor of f8a1c2d3e4b5, so main itself carried two heads.

Neither line is rewritten. This branch's series now starts at f8a1c2d3e4b5 (its first revision,
fe2026112616, was unapplied anywhere, so re-pointing it is free) and ends here, joined to main's
line. A database at f8a1c2d3e4b5 or at fe2026112609 applies whatever it is missing and lands here;
a fresh database runs both lines and joins them the same way.
"""

from collections.abc import Sequence

revision: str = "fe2026112615"
down_revision: tuple[str, str] = ("fe2026112614", "fe2026112609")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change: the two lines are independent and both already applied."""


def downgrade() -> None:
    """No schema change: splitting the heads again would abort the next upgrade."""
