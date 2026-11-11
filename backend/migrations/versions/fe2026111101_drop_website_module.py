"""drop the in-house website builder (tables and SECURITY DEFINER functions).

Revision ID: fe2026111101
Revises: fe2026110508
Create Date: 2026-11-11 19:30:00.000000

The in-house website builder (modules/website) is removed: websites are now sold and run by
the standalone Fihrist Sites platform, and Fihrist only presents them. This migration drops the
six tables and the three helper functions that module created in fe2026110505/06/08.

SAFETY. A migration that drops tables must not destroy data nobody looked at. If ANY of the six
tables holds a row, this raises and drops NOTHING, so a deployment that unexpectedly has merchant
websites stops here instead of silently deleting them. (Production held 0 rows in every table
when this was written.)

The earlier revisions stay in the chain untouched: they are history, and the signup-visitor
migration sits between them.

DOWNGRADE is deliberately a no-op that refuses to pretend: recreating the module's schema would
need the deleted models. Restore from a backup instead.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111101"
down_revision: str | None = "fe2026110508"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Child tables first: FK order, so no CASCADE is needed or used.
_TABLES = (
    "website_published_sites",
    "website_purchases",
    "website_page_sections",
    "website_pages",
    "website_versions",
    "websites",
)

_FUNCTIONS = (
    "public.admin_website_purchases()",
    "public.resolve_website_purchase_tenant(uuid)",
    "public.website_slug_taken(text)",
)


def _refuse_if_populated(table: str) -> str:
    """One DO block per table: raise (aborting the whole transaction) when the table has rows.

    A table that does not exist is skipped, so a database that never had the website builder still
    upgrades. The check runs in SQL, inside the migration's own transaction, so there is no window
    between "looked empty" and "dropped".
    """
    return f"""DO $guard$
BEGIN
  IF to_regclass('public.{table}') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM public.{table}) THEN
      RAISE EXCEPTION 'refusing to drop public.{table}: it holds rows. Export or migrate the website builder data first; nothing was dropped.';
    END IF;
  END IF;
END
$guard$"""


def upgrade() -> None:
    # Refuse to destroy data. Every guard runs before the first DROP.
    for table in _TABLES:
        op.execute(_refuse_if_populated(table))

    for fn in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS public.{table}")


def downgrade() -> None:
    raise RuntimeError(
        "fe2026111101 dropped the website builder's schema and cannot be reversed by a migration. "
        "Restore the database from a backup taken before this revision."
    )
