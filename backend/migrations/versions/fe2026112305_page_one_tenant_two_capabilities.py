"""one Page, one workspace, two capabilities: Facebook and Messenger may share a Page

Revision ID: fe2026112305
Revises: fe2026112304
Create Date: 2026-11-23 22:30:00.000000

``fe2026112302`` keyed the Page alone across Facebook and Messenger. That made the two functions
impossible to hold together: linking Messenger on a Page and then Facebook on the same Page by the
SAME workspace hit the unique index, the link failed, and the failure path then took the app's
subscription off the Page, cutting the Messenger webhooks the first link depended on.

The real rule is narrower. One Page may belong to ONE workspace only (Meta delivers a Page's
webhooks to one app callback, so two workspaces on one Page would both think they own it), but that
workspace may run Facebook Management and Messenger on it side by side. So:

* the unique index is keyed on (Page, provider): one Page cannot carry the same function twice;
* a trigger refuses a SECOND workspace on a Page another workspace already holds, whatever the
  function. A plain unique index cannot say "same tenant only", so the rule lives in the database
  where a race between two API instances cannot get around it.

Pages already linked as two active rows by the same workspace need no data change: they are exactly
what this now allows. Two rows for one Page in DIFFERENT workspaces would already have violated the
previous index, so none can exist.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112305"
down_revision: str | None = "fe2026112304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAGE_PROVIDER_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_page_provider
    ON public.integrations (provider, (COALESCE(config->>'page_id', config->>'account_id')))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND provider IN ('messenger', 'facebook')
   AND COALESCE(config->>'page_id', config->>'account_id') IS NOT NULL
"""

_TENANT_FUNCTION = """
CREATE OR REPLACE FUNCTION public.integrations_one_tenant_per_page() RETURNS trigger AS $$
DECLARE
    page text;
BEGIN
    IF NEW.kind <> 'channel'
       OR NEW.provider NOT IN ('messenger', 'facebook')
       OR NEW.status NOT IN ('active', 'connected') THEN
        RETURN NEW;
    END IF;
    page := COALESCE(NEW.config->>'page_id', NEW.config->>'account_id');
    IF page IS NULL THEN
        RETURN NEW;
    END IF;
    -- Two workspaces linking the same Page at once must not both pass this check.
    PERFORM pg_advisory_xact_lock(hashtextextended('meta_page_tenant:' || page, 0));
    IF EXISTS (
        SELECT 1
          FROM public.integrations other
         WHERE other.id <> NEW.id
           AND other.tenant_id <> NEW.tenant_id
           AND other.kind = 'channel'
           AND other.provider IN ('messenger', 'facebook')
           AND other.status IN ('active', 'connected')
           AND COALESCE(other.config->>'page_id', other.config->>'account_id') = page
    ) THEN
        RAISE EXCEPTION 'this Page is already connected by another workspace'
            USING ERRCODE = '23505', CONSTRAINT = 'uq_integrations_active_page_identity';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER trg_integrations_one_tenant_per_page
    BEFORE INSERT OR UPDATE OF config, status, provider, kind, tenant_id ON public.integrations
    FOR EACH ROW EXECUTE FUNCTION public.integrations_one_tenant_per_page()
"""

_PREVIOUS_PAGE_INDEX = """
CREATE UNIQUE INDEX uq_integrations_active_page_identity
    ON public.integrations ((
        CASE WHEN provider IN ('messenger', 'facebook')
             THEN COALESCE(config->>'page_id', config->>'account_id') END
    ))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND provider IN ('messenger', 'facebook')
   AND COALESCE(config->>'page_id', config->>'account_id') IS NOT NULL
"""


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_page_identity")
    op.execute(_PAGE_PROVIDER_INDEX)
    op.execute(_TENANT_FUNCTION)
    op.execute("DROP TRIGGER IF EXISTS trg_integrations_one_tenant_per_page ON public.integrations")
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_integrations_one_tenant_per_page ON public.integrations")
    op.execute("DROP FUNCTION IF EXISTS public.integrations_one_tenant_per_page()")
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_page_provider")
    # The previous index forbids two rows for one Page, so it cannot be restored while a workspace
    # holds both functions on a Page. Say so instead of failing half-way through.
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.integrations
         WHERE provider IN ('messenger', 'facebook') AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND COALESCE(config->>'page_id', config->>'account_id') IS NOT NULL
         GROUP BY COALESCE(config->>'page_id', config->>'account_id')
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'a Page runs both Facebook and Messenger; disconnect one before downgrading';
    END IF;
END
$$
"""
    )
    op.execute(_PREVIOUS_PAGE_INDEX)
