"""use Telegram bot ID for global channel identity uniqueness

Revision ID: fbc2a817d901
Revises: db6022a13691
Create Date: 2026-10-02 18:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "fbc2a817d901"
down_revision: str | None = "db6022a13691"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DUPLICATE_PREFLIGHT = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.integrations
         WHERE provider = 'telegram'
           AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND config->>'bot_id' IS NOT NULL
         GROUP BY config->>'bot_id'
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active Telegram bot identities; reconcile integrations before deploying';
    END IF;
END
$$;
"""

_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, (
        CASE
            WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
            WHEN provider IN ('messenger', 'instagram') THEN config->>'account_id'
            WHEN provider = 'telegram' THEN config->>'bot_id'
            WHEN provider = 'webchat' THEN config->>'public_key'
        END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram') AND config->>'account_id' IS NOT NULL) OR
       (provider = 'telegram' AND config->>'bot_id' IS NOT NULL) OR
       (provider = 'webchat' AND config->>'public_key' IS NOT NULL)
   )
"""

_PREVIOUS_UNIQUE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, (
        CASE
            WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
            WHEN provider IN ('messenger', 'instagram') THEN config->>'account_id'
            WHEN provider IN ('telegram', 'webchat') THEN config->>'public_key'
        END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram') AND config->>'account_id' IS NOT NULL) OR
       (provider IN ('telegram', 'webchat') AND config->>'public_key' IS NOT NULL)
   )
"""


def upgrade() -> None:
    # Resolve known duplicates explicitly before replacing the existing index.
    # The migration is transactional, so a conflict preserves the old index.
    op.execute(_DUPLICATE_PREFLIGHT)
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity")
    op.execute(_UNIQUE_INDEX)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity")
    op.execute(_PREVIOUS_UNIQUE_INDEX)
