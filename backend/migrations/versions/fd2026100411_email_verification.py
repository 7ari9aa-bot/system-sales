"""Email verification — the account pre-hijack guard (external audit, finding 3).

The attack: an attacker registers a victim's email BEFORE the victim signs up.
register() never verified email, so the attacker held a live account named with
the victim's address; when an admin later invites that address, the invitation
bound the role to the ATTACKER's account — and the victim's future signup hit
"email already registered". One column plus one flow closes it: an account must
have PROVEN inbox control before accept_invitation will bind a membership to
it, and proving inbox control is exactly what a verification link, a completed
password reset, or an invitation token redeemed for a NEW account each do.

What this migration ships:

- ``users.email_verified`` (boolean, NOT NULL, server_default false). The
  server_default covers INSERTs that do not name the column (register creates
  unverified accounts; accept_invitation creates verified ones — the invitation
  token arrives in the invitee's inbox, so redeeming it IS inbox proof).
  Existing rows are then backfilled to true: an account that predates the
  column can neither prove nor disprove inbox control, and defaulting every
  existing user to unverified would refuse every pending invitation in
  production until each of them completed a reset. New registrations are
  unverified from here on — that is the point.
- ``email_verification_tokens`` — the durable queue behind the verification
  email, a structural copy of ``password_reset_tokens`` (fd2026100401): sha256
  hash for validation, encrypted raw token only while delivery is pending,
  leased retry state for the delivery worker. Like the reset table it is a
  GLOBAL pre-GUC possession table (verification runs before any tenant context
  exists), so it gets the same RLS posture fd2026100410 gave its five auth
  tables: permissive SELECT/INSERT/UPDATE — the request path, the token
  consumer and the delivery worker all run pre-GUC and the possession
  credential is a query argument invisible to a policy — and NO DELETE policy,
  so RLS denies purges outright.

Every sales_app-dependent statement is guarded on the role existing: CI runs
alembic BEFORE provision creates it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fd2026100411"
down_revision: str | None = "fd2026100410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _grant_if_role_exists(statements: tuple[str, ...]) -> None:
    for statement in statements:
        op.execute(
            f"""DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                EXECUTE {statement!r};
              END IF;
            END $$"""
        )


def upgrade() -> None:
    # --- the column --------------------------------------------------------
    # ADD COLUMN with a constant default is metadata-only in Postgres: no table
    # rewrite, no lock outlasting the catalog change, and every existing row
    # reads as false the instant the column exists. The backfill below then
    # grandfathers those rows to true (see the module docstring).
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute("UPDATE users SET email_verified = true")

    # --- the verification-token queue --------------------------------------
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id",
        "email_verification_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_verification_user_requested",
        "email_verification_tokens",
        ["user_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_verification_delivery_due",
        "email_verification_tokens",
        ["next_attempt_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text(
            "sent_at IS NULL AND consumed_at IS NULL AND delivery_failed_at IS NULL"
        ),
    )

    # --- RLS: same posture as password_reset_tokens (fd2026100410) ---------
    op.execute("ALTER TABLE public.email_verification_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.email_verification_tokens FORCE ROW LEVEL SECURITY")
    # Request (queue), consumer (verify by hash) and delivery worker (lease
    # sweep) all run pre-GUC; the hash/token IS the possession credential.
    op.execute("DROP POLICY IF EXISTS evt_possession_read ON public.email_verification_tokens")
    op.execute(
        """CREATE POLICY evt_possession_read ON public.email_verification_tokens
           FOR SELECT USING (true)"""
    )
    op.execute("DROP POLICY IF EXISTS evt_request_insert ON public.email_verification_tokens")
    op.execute(
        """CREATE POLICY evt_request_insert ON public.email_verification_tokens
           FOR INSERT WITH CHECK (true)"""
    )
    op.execute("DROP POLICY IF EXISTS evt_consume_update ON public.email_verification_tokens")
    op.execute(
        """CREATE POLICY evt_consume_update ON public.email_verification_tokens
           FOR UPDATE USING (true)"""
    )
    # No DELETE policy — RLS denies it outright; nothing purges these rows,
    # mirroring password_reset_tokens (expiry/consumption are terminal states).

    # --- runtime-role privileges -------------------------------------------
    # fd2026100409's blanket revokes and provision.py's grants predate this
    # table, so the new table needs its own (conditional) grants: the runtime
    # role must queue, sweep and consume rows; nothing else may.
    _grant_if_role_exists(
        (
            "GRANT SELECT, INSERT, UPDATE ON public.email_verification_tokens TO sales_app",
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.email_verification_tokens")
    op.drop_column("users", "email_verified")
