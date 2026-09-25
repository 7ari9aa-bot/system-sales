"""Name the 22 unnamed constraints on this branch's slice (register O3, one slice)

Revision ID: c3f4e5a6b7d8
Revises: b2e3d4f5a6c7
Create Date: 2026-09-24

Register O3: "downgrade chain broken by ~145 unnamed constraints". The mechanism
is concrete and reproducible — migrations that wrote

    op.create_foreign_key(None, "customers", "workspaces", ["workspace_id"], ["id"])

render an ANONYMOUS constraint, Postgres invents a name for it
(`customers_workspace_id_fkey`), and the paired downgrade line

    op.drop_constraint(None, "customers", type_="foreignkey")

cannot be rendered at all. Alembic says so in the file itself:

    # WARNING: constraint name is None; this directive will fail as rendered.

So a rollback aborts. 145 is the whole-repo figure and it is not this
revision's job — this one names the six tables the current branch actually
touches (workflow_versions, workflows, customers, products, knowledge_items,
segments), which is 22 constraints, counted from the DDL that created them:
stage1 `0b79f7470c1a` (6 PK/FK on customers/products/knowledge_items), `48528b41d6db`
(the W2-a workspace/location FKs), `49303e2e2dd0` (the M12 merge FK),
`6cd2037d7891` (the automation domain), `d4a7c1e9f0b5` (§151 Q4 scope FKs on
workflows) and `b2c3d4e5f6a7` (segments).

Why RENAME instead of a naming convention in env.py
---------------------------------------------------
`migrations/env.py` has no ``naming_convention``, which is the root cause. Adding
one is the real fix for FUTURE autogenerate, but it changes what every
outstanding ``--autogenerate`` diff emits for eleven other agents on this branch
at once, and it does nothing for the 22 names already in the live catalogue. So
this revision renames what exists; the env.py recommendation is reported instead
of applied here.

The names are DERIVED, never transcribed. ``constraint_names`` reproduces
Postgres's own ``ChooseConstraintName`` rule (``<table>_pkey``,
``<table>_<column>_fkey``) on one side and the repo convention (``pk_<table>``,
``fk_<table>_<column>_<referent>``) on the other, so a pair cannot be pointed at
the wrong constraint by a typo — the only thing that needed to be typed by hand
is which constraints are on the list, and a guard asserts that list against the
migrations that created it.

Replay-safe in both directions: a target name already present is skipped, so a
re-run after a partial failure is harmless; NEITHER name present aborts, because
then the assumption about the live schema is simply wrong and inventing a
constraint silently would make the next rollback worse, not better.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f4e5a6b7d8"
down_revision: str | None = "b2e3d4f5a6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, kind, local columns, referent table)  — kind: "p" primary, "f" foreign.
# Every entry here is a constraint some migration created WITHOUT a name, so
# Postgres named it. Constraints that already had explicit names
# (`uq_customers_tenant_phone`, `uq_products_tenant_slug`,
# `fk_segments_tenant_id_tenants`, and everything a1f2c3d4e5b6 adds) are absent
# by design.
_RENAME_SPECS: frozenset[tuple[str, str, tuple[str, ...], str | None]] = frozenset({
    # customers — stage1 PK + tenant FK; W2-a scope FKs; M12 merge FK
    ("customers", "p", ("id",), None),
    ("customers", "f", ("tenant_id",), "tenants"),
    ("customers", "f", ("workspace_id",), "workspaces"),
    ("customers", "f", ("location_id",), "locations"),
    ("customers", "f", ("merged_into_customer_id",), "customers"),
    # knowledge_items — stage1 PK + tenant FK; W2-a scope FKs
    ("knowledge_items", "p", ("id",), None),
    ("knowledge_items", "f", ("tenant_id",), "tenants"),
    ("knowledge_items", "f", ("workspace_id",), "workspaces"),
    ("knowledge_items", "f", ("location_id",), "locations"),
    # products — stage1 PK + three FKs; W2-a scope FKs
    ("products", "p", ("id",), None),
    ("products", "f", ("tenant_id",), "tenants"),
    ("products", "f", ("brand_id",), "brands"),
    ("products", "f", ("category_id",), "categories"),
    ("products", "f", ("workspace_id",), "workspaces"),
    ("products", "f", ("location_id",), "locations"),
    # segments — created named EXCEPT the primary key
    ("segments", "p", ("id",), None),
    # workflow_versions — created nameless by the automation domain migration
    ("workflow_versions", "p", ("id",), None),
    ("workflow_versions", "f", ("workflow_id",), "workflows"),
    # workflows — stage1-style PK + tenant FK; §151 Q4 scope FKs
    ("workflows", "p", ("id",), None),
    ("workflows", "f", ("tenant_id",), "tenants"),
    ("workflows", "f", ("workspace_id",), "workspaces"),
    ("workflows", "f", ("location_id",), "locations"),
})


def constraint_names(
    table: str, kind: str, columns: Sequence[str], referent: str | None
) -> tuple[str, str]:
    """(name Postgres invented, name this convention wants).

    The left half mirrors ``ChooseConstraintName`` in
    ``src/backend/catalog/heap.c``: a generated constraint name is
    ``<table>_<column-name(s)>_suffix``, where the suffix is ``pkey`` for a
    primary key and ``fkey`` for a foreign key. Single-column here, so the
    ``multiple_columns`` form never applies.
    """
    if kind == "p":
        return f"{table}_pkey", f"pk_{table}"
    if kind != "f":
        raise ValueError(f"unknown constraint kind {kind!r} for {table}")
    joined = "_".join(columns)
    if referent is None:
        raise ValueError(f"foreign key on {table} needs a referent table")
    return f"{table}_{joined}_fkey", f"fk_{table}_{joined}_{referent}"


def _rename_pairs(*, reverse: bool = False) -> list[tuple[str, str, str]]:
    """Deterministic (table, from, to) list — sorted so the SQL is reproducible."""
    pairs = []
    for table, kind, columns, referent in sorted(_RENAME_SPECS):
        current, wanted = constraint_names(table, kind, columns, referent)
        pairs.append((table, wanted, current) if reverse else (table, current, wanted))
    return pairs


def _rename_block(pairs: list[tuple[str, str, str]]) -> str:
    """One plpgsql DO block, hence one statement, hence one op.execute()."""
    values = ",\n".join(
        f"            ('{table}', '{old}', '{new}')" for table, old, new in pairs
    )
    return f"""
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
{values}
        ) AS t(tbl, old_name, new_name)
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_constraint c
              JOIN pg_namespace n ON n.oid = c.connamespace
             WHERE n.nspname = 'public'
               AND c.conrelid = ('public.' || r.tbl)::regclass
               AND c.conname = r.new_name
        ) THEN
            -- Already renamed: a re-run after a partial failure must be a no-op.
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
              JOIN pg_namespace n ON n.oid = c.connamespace
             WHERE n.nspname = 'public'
               AND c.conrelid = ('public.' || r.tbl)::regclass
               AND c.conname = r.old_name
        ) THEN
            RAISE EXCEPTION
                'constraint % on public.% not found, but % was expected to be renamed to % — the live schema does not match this revision',
                r.old_name, r.tbl, r.old_name, r.new_name;
        END IF;
        EXECUTE format(
            'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
            r.tbl, r.old_name, r.new_name
        );
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(_rename_block(_rename_pairs()))


def downgrade() -> None:
    # Give back exactly the names Postgres invented, so an earlier revision's
    # downgrade — which never had a name to work with — is no worse than before.
    op.execute(_rename_block(_rename_pairs(reverse=True)))
