"""users.email is matched case-folded — enforce it at the schema level.

Every identity path now writes and looks up lower(email); this unique
functional index closes the race for good: two accounts differing only by
case can never coexist, regardless of which service path writes them.

Fails loudly if the existing data already holds case-duplicates — that is
the correct signal BEFORE the first real tenant, not after.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fd2026100407"
down_revision: str | None = "fd2026100406"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_lower", table_name="users")
