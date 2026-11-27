"""Join the voice line and the invitation line: one head again.

The voice migrations branch off fe2026112617, and the invitation migrations continued from the
same point, so `alembic upgrade head` refused with two heads while production already sat on the
invitation head. This revision joins them: it changes no schema, it only makes one head exist so
the upgrade can be applied in order and the version stamp can move.
"""

from __future__ import annotations

revision: str = "fe2026112703"
down_revision: tuple[str, str] | None = ("fe2026112619", "fe2026112702")
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """No DDL: the two lines already exist, only the graph needs joining."""


def downgrade() -> None:
    """Splitting the lines again is a code change, not a data change."""
