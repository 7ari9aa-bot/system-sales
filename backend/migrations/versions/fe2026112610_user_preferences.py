"""The person's own preferences: language, appearance, timezone, dates, landing page.

Revision ID: fe2026112606
Revises: fe2026112605

These five facts existed as browser state — a localStorage key for the theme and a
localStorage key for the language — so they followed the BROWSER, not the person:
the same account on the till and on a phone could disagree, and clearing site data
reset them. They are small, self-owned and never identity keys, so they live as
nullable columns on ``users`` rather than in a second table: one row already loads
with every authenticated request, and NULL means "follow the default", which is
what makes a fresh account behave exactly as it did before this migration.

Deliberate choices:

- ``users.timezone`` is separate from ``tenants.timezone``. A shop counts its day in
  its own zone (§47); a person travelling to Cairo should see their own clock, and
  moving a branch must never silently move their times.
- Every value is bounded by a CHECK at the database AND validated in the service.
  ``theme``, ``locale`` and ``date_format`` are closed sets; ``timezone`` is only
  shape-checked here because tzdata lives in Python, so resolvability is asserted
  by ``identity.services.settings.timezone_refusal`` on write.
- ``default_page`` is stored as a route the API WHITELISTS. It is read by the shell
  to decide where "/" lands, so an unvalidated value would be a redirect primitive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112610"
down_revision: str | None = "fe2026112616"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))
    op.add_column("users", sa.Column("theme", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("date_format", sa.String(length=8), nullable=True))
    op.add_column("users", sa.Column("default_page", sa.String(length=64), nullable=True))

    op.create_check_constraint(
        "ck_users_locale", "users", "locale IS NULL OR locale IN ('ar', 'en')"
    )
    op.create_check_constraint(
        "ck_users_theme", "users", "theme IS NULL OR theme IN ('system', 'light', 'dark')"
    )
    op.create_check_constraint(
        "ck_users_date_format",
        "users",
        "date_format IS NULL OR date_format IN ('dmy', 'mdy', 'ymd')",
    )
    # Shape only: tzdata is not in Postgres, so "resolvable" is asserted in Python.
    op.create_check_constraint(
        "ck_users_timezone_shape",
        "users",
        "timezone IS NULL OR timezone ~ '^[A-Za-z][A-Za-z0-9_/+-]*$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_timezone_shape", "users", type_="check")
    op.drop_constraint("ck_users_date_format", "users", type_="check")
    op.drop_constraint("ck_users_theme", "users", type_="check")
    op.drop_constraint("ck_users_locale", "users", type_="check")
    op.drop_column("users", "default_page")
    op.drop_column("users", "date_format")
    op.drop_column("users", "timezone")
    op.drop_column("users", "theme")
    op.drop_column("users", "locale")
