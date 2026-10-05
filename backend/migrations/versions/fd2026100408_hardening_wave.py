"""Hardening wave: notification dedup uniqueness + authority-plane FKs.

Two external-audit findings, both real:

1. NotificationService.create is check-then-insert on dedup_key — two
   concurrent producers could both see "absent" and insert duplicates. The
   partial unique index makes the database the arbiter (the service's
   IntegrityError handler returns the winner's row).

2. The v12 authority-plane tables carried NO foreign keys: leases could
   outlive their grant, reservations their budget. The intra-domain
   references are now enforced (decision_id/actor_id stay unenforced —
   they are optional cross-module pointers by design).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fd2026100408"
down_revision: str | None = "fd2026100407"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Notification dedup: the database becomes the race arbiter. Partial —
    # dedup_key-less notifications are fire-and-forget by design.
    op.create_index(
        "ix_notifications_tenant_user_dedup",
        "notifications",
        ["tenant_id", "user_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    # Authority plane: the intra-domain references become real constraints.
    op.create_foreign_key(
        "fk_authority_leases_grant",
        "authority_leases",
        "capability_grants",
        ["grant_id"],
        ["grant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_budget_reservations_budget",
        "budget_reservations",
        "autonomy_budgets",
        ["budget_id"],
        ["budget_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_autonomy_budgets_parent",
        "autonomy_budgets",
        "autonomy_budgets",
        ["parent_budget_id"],
        ["budget_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_autonomy_budgets_parent", "autonomy_budgets", type_="foreignkey")
    op.drop_constraint("fk_budget_reservations_budget", "budget_reservations", type_="foreignkey")
    op.drop_constraint("fk_authority_leases_grant", "authority_leases", type_="foreignkey")
    op.drop_index("ix_notifications_tenant_user_dedup", table_name="notifications")
