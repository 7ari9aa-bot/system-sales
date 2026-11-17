"""merge the two heads: the owner assistant prompt chain and the POS / supply-chain chain.

Revision ID: fe2026111729
Revises: fe2026111725 (owner assistant prompt) + fe2026111728 (POS cash movements)
Create Date: 2026-11-18 00:10:00.000000

WHY. Two branches left fe2026111621 on the same day and each added its own head:
fe2026111701 -> 723 -> 724 -> 725 (inbox list state, attachment kind, the assistant prompt) and
fe2026111622 -> ... -> 627 -> 728 (country layer, supply chain, e-invoice, POS cash). With two
heads ``alembic upgrade head`` refuses to run, so the service exited at start (code 255) on every
deploy of bbba4d2 and the shop was down.

This file changes nothing in the database. It only gives the two chains one tip, so a database on
either branch upgrades by running the other branch and then this no-op.
"""

from collections.abc import Sequence

revision: str = "fe2026111729"
down_revision: tuple[str, str] = ("fe2026111725", "fe2026111728")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
