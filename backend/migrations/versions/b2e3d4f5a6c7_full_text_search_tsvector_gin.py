"""Real full-text search for customers / products / knowledge items (§45 / A7)

Revision ID: b2e3d4f5a6c7
Revises: a1f2c3d4e5b6
Create Date: 2026-09-24

spec §45 asked for full-text search. What shipped is ``ILIKE '%…%'``, and
``app/core/search.py`` says so itself: "This is NOT full-text search, whatever
the name suggests: no tsvector, no trigram index, no relevance ranking —
customers come back alphabetical and products in heap order."

This revision adds the missing half as STORED generated tsvector columns with
GIN indexes. It deliberately does NOT remove the ILIKE path — see below.

Why the ``simple`` configuration — and why it is not a style choice
-------------------------------------------------------------------
A ``GENERATED ALWAYS AS (...) STORED`` column requires an IMMUTABLE expression.
``to_tsvector('simple', x)`` — the TWO-argument form, configuration spelled out
as a literal — is IMMUTABLE. ``to_tsvector(x)``, the one-argument form that
takes its configuration from ``default_text_search_config``, is only STABLE, and
Postgres refuses it outright:

    functions in index expression must be marked IMMUTABLE

So the configuration MUST be pinned for this column to exist at all. That
settles the mechanics; the remaining question is which configuration to pin,
and the content answers it. This is an Arabic+Latin storefront: merchant
product titles and customer names mix both scripts in one column, often in one
string. ``english`` stems Latin (``running`` -> ``run``) and applies Latin
stopwords to Arabic text it cannot parse; ``arabic`` stems Arabic and mangles
the Latin that sits in the same title; ``pg_catalog.default`` is worse than
either because it makes a STORED column's CONTENT depend on whichever
``search_path``/``default_text_search_config`` the connecting role happens to
set — a per-deployment, invisible input to an immutable column.
``simple`` tokenises and lowercases both scripts and stems neither. It trades
morphological matching (which is where Arabic gains most from stemming) for
never answering a search with text analysed under the wrong language's rules,
and it is the only option whose result is a function of the row and nothing
else. Ranking is recovered from the lost matching by ``setweight``: title hits
are weighted 'A' and contact details 'B'/'C', which is what ``ts_rank`` needs
to order the results ILIKE never could.

Why ILIKE stays
---------------
``to_tsvector`` cannot answer a partial contact. ``phone ILIKE '%5521%'`` must
match ``+201005521444`` because M12 stores canonical contacts and users type
fragments — but the whole phone number is ONE token, and tsvector matches
tokens, not substrings. So the containment path remains load-bearing and the
read side must OR the two. (The right long-term answer for fragments is a
``pg_trgm`` GIN index on the raw columns; that is a separate decision because
it is an extension, and is recorded as such rather than smuggled in here.)

The rewrite cost: a STORED generated column rewrites the table and holds
ACCESS EXCLUSIVE for the duration. Development stage, no live traffic — the
note is for whoever replays this onto a database that has both.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2e3d4f5a6c7"
down_revision: str | None = "a1f2c3d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> the GENERATED ALWAYS expression, as one string.
#
# These literals are ALSO written into the ORM models as sa.Computed(...).
# They cannot be shared — a migration must not import application code it is
# meant to be able to replay without it — so tests/test_tenancy_and_fts_schema_debt.py
# pins them equal in both places. The column-parity guard in test_migrations.py
# compares column NAMES only and would not see an expression drift.
_SEARCH_TS: dict[str, str] = {
    "customers": (
        "(setweight(to_tsvector('simple', coalesce(name, '')), 'A') "
        "|| setweight(to_tsvector('simple', coalesce(email, '')), 'B') "
        "|| setweight(to_tsvector('simple', coalesce(phone, '')), 'C'))"
    ),
    "products": (
        "(setweight(to_tsvector('simple', coalesce(title, '')), 'A') "
        "|| setweight(to_tsvector('simple', coalesce(description, '')), 'B'))"
    ),
    "knowledge_items": (
        "(setweight(to_tsvector('simple', coalesce(title, '')), 'A') "
        "|| setweight(to_tsvector('simple', coalesce(content, '')), 'B'))"
    ),
}


# WHY THE TABLES ARE WRITTEN OUT INSTEAD OF LOOPED OVER
# -----------------------------------------------------------------------------
# `test_migrations.test_every_model_column_is_created_by_a_migration` reads this
# file with `ast` and records (table, column) pairs from `op.add_column` calls
# whose FIRST argument is a string CONSTANT. Written as
# `for table in _SEARCH_TS: op.add_column(table, ...)` the guard sees a Name,
# not a table, and silently stops checking these three columns — which is
# precisely the blind spot that let the notifications/ai_budget_reservations
# drift through. So: the expressions stay in one dict (shared with the ORM
# models) but every op call is literal. Verbose on purpose; the alternative is a
# guard that passes because it can no longer see anything.
def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "search_ts",
            postgresql.TSVECTOR,
            sa.Computed(_SEARCH_TS["customers"], persisted=True),
            nullable=True,
        ),
    )
    # A tsvector with no GIN index is a write penalty and nothing else.
    op.create_index(
        "ix_customers_search_ts", "customers", ["search_ts"], postgresql_using="gin"
    )

    op.add_column(
        "products",
        sa.Column(
            "search_ts",
            postgresql.TSVECTOR,
            sa.Computed(_SEARCH_TS["products"], persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_products_search_ts", "products", ["search_ts"], postgresql_using="gin"
    )

    op.add_column(
        "knowledge_items",
        sa.Column(
            "search_ts",
            postgresql.TSVECTOR,
            sa.Computed(_SEARCH_TS["knowledge_items"], persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_knowledge_items_search_ts",
        "knowledge_items",
        ["search_ts"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Reverse order, and the index goes before the column it sits on.
    op.drop_index("ix_knowledge_items_search_ts", table_name="knowledge_items")
    op.drop_column("knowledge_items", "search_ts")

    op.drop_index("ix_products_search_ts", table_name="products")
    op.drop_column("products", "search_ts")

    op.drop_index("ix_customers_search_ts", table_name="customers")
    op.drop_column("customers", "search_ts")
