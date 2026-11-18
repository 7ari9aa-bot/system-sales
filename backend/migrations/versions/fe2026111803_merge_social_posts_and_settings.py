"""merge the two heads: Instagram social posts (main) and the settings engine (this branch).

Revision ID: fe2026111803
Revises: fe2026111731 (social posts and comment moderation) + fe2026111802 (settings unique nulls)
Create Date: 2026-11-18 18:00:00.000000

WHY. Both chains left the same ancestor on the same day: main added
fe2026111731 (Instagram posts) while this branch added fe2026111801 -> 802 (the settings
configuration engine). With two heads ``alembic upgrade head`` refuses to run and the service
exits at start, so the two chains need one tip before either can deploy.

This file changes nothing in the database.
"""

from collections.abc import Sequence

revision: str = "fe2026111803"
down_revision: tuple[str, str] = ("fe2026111731", "fe2026111802")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
