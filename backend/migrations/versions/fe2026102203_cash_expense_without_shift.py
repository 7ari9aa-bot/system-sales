"""A cash expense may be recorded without a shift.

Before: cash <=> tied to a shift. Now only "a shift is tied to cash expenses": a non-cash
expense still never carries a shift, but a cash expense may have none (it is a record; no drawer
moved). Existing rows all satisfy the new rule, so nothing is rewritten.

Revision ID: fe2026102203
Revises: fe2026102202
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026102203"
down_revision: str | None = "fe2026102202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_expenses_cash_has_session", "expenses", type_="check")
    op.create_check_constraint(
        "ck_expenses_shift_only_cash",
        "expenses",
        "session_id IS NULL OR payment_method = 'cash'",
    )


def downgrade() -> None:
    # Shiftless cash expenses cannot satisfy the old rule: they were never tied to a drawer, so
    # the honest way back is to refuse rather than invent a shift for them.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM expenses "
        "WHERE payment_method = 'cash' AND session_id IS NULL) THEN "
        "RAISE EXCEPTION 'cannot downgrade: cash expenses without a shift exist'; "
        "END IF; END $$"
    )
    op.drop_constraint("ck_expenses_shift_only_cash", "expenses", type_="check")
    op.create_check_constraint(
        "ck_expenses_cash_has_session",
        "expenses",
        "(payment_method = 'cash') = (session_id IS NOT NULL)",
    )
