"""Platform announcements: the owner console's broadcast to merchants (Slice B).

Revision ID: fe2026110503
Revises: fe2026110502

The owner console composes a notice ("deployment tonight at 22:00"), targets it
(all tenants or an explicit list), and the merchant dashboard renders it as a
slim Supabase-style banner until the user dismisses it.

Deliberate modelling decisions:

- ``platform_announcements`` is GLOBAL (no ``tenant_id``): the platform owns the
  rows and every tenant only ever READS the resolved subset. There is no RLS
  here for the same reason ``plans`` has none — tenant scoping would be
  decoration on a table nobody reads per-tenant-writable. The audience filter
  lives in ``audience`` JSONB: ``NULL`` means "every tenant", otherwise
  ``{"tenant_ids": [...]}``. The service filters in Python, not with a JSONB
  operator, so an empty ``tenant_ids`` list can never accidentally mean "all".
- ``platform_announcement_dismissals`` is per (announcement, user), NOT per
  tenant: two staff members of one shop dismiss independently, and the banner
  returns for a user who never dismissed it. The composite PK is the
  idempotency arbiter — a double-dismiss is an ``ON CONFLICT DO NOTHING``.
- Lifecycle is derived, not stored: a row is LIVE when ``is_active`` AND
  ``now()`` is inside ``[starts_at, ends_at)``. The console computes status for
  its own table view; the merchant read path never trusts a status string that
  could drift from the clock.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026110503"
down_revision: str | None = "fe2026110502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT_SALES_APP = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {grant};
    END IF;
END
$$;"""


def _grant_sales_app(grant: str) -> str:
    return _GRANT_SALES_APP.format(grant=grant)


def upgrade() -> None:
    op.create_table(
        "platform_announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=15), server_default="info", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cta_label", sa.String(length=127), nullable=True),
        sa.Column("cta_url", sa.Text(), nullable=True),
        sa.Column("audience", postgresql.JSONB(), nullable=True),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_platform_announcements_active_window",
        "platform_announcements",
        ["is_active", "starts_at"],
    )
    op.create_check_constraint(
        "ck_platform_announcements_kind",
        "platform_announcements",
        "kind IN ('info', 'warning', 'maintenance', 'update')",
    )
    op.create_check_constraint(
        "ck_platform_announcements_window",
        "platform_announcements",
        "ends_at IS NULL OR ends_at > starts_at",
    )

    op.create_table(
        "platform_announcement_dismissals",
        sa.Column(
            "announcement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_announcements.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_platform_announcement_dismissals_user",
        "platform_announcement_dismissals",
        ["user_id"],
    )

    # Least privilege on a global table with no RLS backstop: the app role
    # only ever READS announcements (the owner console writes them via the
    # management API) and only ever INSERTS dismissals — it cannot edit or
    # retract a notice even if a code path went wrong.
    op.execute(
        _grant_sales_app(
            "GRANT SELECT ON platform_announcements TO sales_app"
        )
    )
    op.execute(
        _grant_sales_app(
            "GRANT SELECT, INSERT ON platform_announcement_dismissals TO sales_app"
        )
    )


def downgrade() -> None:
    op.drop_table("platform_announcement_dismissals")
    op.drop_table("platform_announcements")
