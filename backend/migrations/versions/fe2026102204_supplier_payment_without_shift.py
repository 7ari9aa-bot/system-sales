"""A cash supplier payment may be recorded without a shift.

Before: cash <=> tied to a shift. Now only "a shift belongs to a cash payment only": a non-cash
payment still never carries a shift, but a cash one may have none (it is a record; no drawer
moved). Existing rows all satisfy the new rule, so nothing is rewritten.

Revision ID: fe2026102204
Revises: fe2026102203
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026102204"
down_revision: str | None = "fe2026102203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_supplier_payments_cash_has_session", "supplier_payments", type_="check")
    op.create_check_constraint(
        "ck_supplier_payments_shift_only_cash",
        "supplier_payments",
        "session_id IS NULL OR method = 'cash'",
    )


def downgrade() -> None:
    # Shiftless cash payments cannot satisfy the old rule: they never touched a drawer, so the
    # honest way back is to refuse rather than invent a shift for them.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM supplier_payments "
        "WHERE method = 'cash' AND session_id IS NULL) THEN "
        "RAISE EXCEPTION 'cannot downgrade: cash supplier payments without a shift exist'; "
        "END IF; END $$"
    )
    op.drop_constraint("ck_supplier_payments_shift_only_cash", "supplier_payments", type_="check")
    op.create_check_constraint(
        "ck_supplier_payments_cash_has_session",
        "supplier_payments",
        "(method = 'cash') = (session_id IS NOT NULL)",
    )
