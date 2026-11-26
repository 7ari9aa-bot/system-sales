"""Account settings: contact fields the person owns, and the closure request.

Revision ID: fe2026112605
Revises: fe2026112604

The "My account" section of settings answers two questions the API could not:
who am I (phone, job title — a name and an email were all the account held), and
how do I leave (there was no way to ask for closure at all).

Deliberate modelling decisions:

- ``users.phone`` and ``users.job_title`` are OPTIONAL and self-owned. They are
  contact/display facts, not identity keys: the email stays the login and the
  address invitations bind to, so nothing here can move an account. No
  ``phone_verified`` flag is added because nothing in this deployment can prove
  a phone number yet (there is no SMS provider); a column that can never become
  true would be a claim the screen cannot honour.
- ``account_closure_requests`` is a REQUEST, not a deletion. A person cannot
  erase an account that other people depend on: the owner of a shop has to hand
  it over first, so the row records intent (``mode``: close or delete), the
  reason, and a lifecycle the platform decides. The API refuses to open one
  while the person is the last owner of a live tenant, and the screen says why.
- One OPEN request per person: a partial unique index on ``user_id`` where
  ``status = 'pending'`` makes a double submit a 409 instead of two rows.
- RLS is self-scoped on ``app.user_id`` (set on every authenticated request by
  the identity dependency), so a request row is invisible to everyone else even
  if a code path forgot its own filter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112616"
down_revision: str | None = "f8a1c2d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"

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
    # ---------------------------------------------------- contact fields -----
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=120), nullable=True))

    # ------------------------------------------------------- closure rows ----
    op.create_table(
        "account_closure_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # close: stop using the account, keep the person's rows for the shops
        # that still reference them. delete: erase the personal data as well.
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
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
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("mode IN ('close', 'delete')", name="ck_account_closure_requests_mode"),
        sa.CheckConstraint(
            "status IN ('pending', 'cancelled', 'rejected', 'completed')",
            name="ck_account_closure_requests_status",
        ),
    )
    op.create_index(
        "ix_account_closure_requests_user",
        "account_closure_requests",
        ["user_id", "created_at"],
    )
    # One OPEN request per person: the second submit loses to the index.
    op.execute(
        """CREATE UNIQUE INDEX uq_account_closure_requests_open
           ON account_closure_requests (user_id)
           WHERE status = 'pending'"""
    )

    op.execute("ALTER TABLE account_closure_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE account_closure_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY account_closure_requests_self_read ON account_closure_requests
            FOR SELECT USING (user_id = {_USER_GUARD})"""
    )
    op.execute(
        f"""CREATE POLICY account_closure_requests_self_insert ON account_closure_requests
            FOR INSERT WITH CHECK (user_id = {_USER_GUARD})"""
    )
    # Cancelling is the only write a person performs on their own request; the
    # platform's decision (rejected/completed) is written by the platform role.
    op.execute(
        f"""CREATE POLICY account_closure_requests_self_cancel ON account_closure_requests
            FOR UPDATE USING (user_id = {_USER_GUARD})
            WITH CHECK (user_id = {_USER_GUARD})"""
    )
    op.execute(
        _grant_sales_app("GRANT SELECT, INSERT, UPDATE ON account_closure_requests TO sales_app")
    )


def downgrade() -> None:
    op.drop_table("account_closure_requests")
    op.drop_column("users", "job_title")
    op.drop_column("users", "phone")
