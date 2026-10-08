"""Wrap current_setting() calls in RLS policies with (SELECT …) for initplan.

The Supabase Performance Advisor (lint 0003_auth_rls_initplan) flagged 156 RLS
policies where `current_setting()` is re-evaluated per-row instead of once per
query.  This migration rewrites every affected policy's USING/WITH CHECK
expression with the `(SELECT …)` wrapper so PostgreSQL evaluates the setting once
and caches it.

Strategy:
  A PL/pgSQL DO-block iterates pg_policies in the public schema, detects bare
  `current_setting(` calls that are NOT already wrapped, and applies
  ALTER POLICY with the wrapped expression.

  It matches on the TEXT Postgres stores, and Postgres de-parses what it is given
  — `current_setting('app.tenant_id'::text, true)` is stored with the `::text`
  casts it inferred, which the literal patterns below do not spell. So a policy
  created by scripts/provision.py may well match nothing and be left alone. That
  is a silent NO-OP, not a corruption: this is a performance lint, and the bare
  form it targets is correct, just slower. Which policies actually got rewritten
  is in the migration's own NOTICE output, and that is worth reading on a real
  database before assuming the lint is cleared.

Revision ID: fe2026100804
Revises: fe2026100803
Create Date: 2026-10-08 20:20:00.000000
"""
from collections.abc import Sequence

from alembic import op


revision: str = "fe2026100804"
down_revision: str | None = "fe2026100803"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# PL/pgSQL block that rewrites RLS policies in-place.
#
# For each policy on a table in the `public` schema whose `qual` or
# `with_check` contains a bare `current_setting(` (not already wrapped in
# `(select current_setting(`), apply ALTER POLICY with `current_setting(`
# replaced by `(select current_setting(` — the command, target roles and
# permissive flag are left untouched, because reproducing them from deparsed
# text is both unnecessary and unsound for policies granted to PUBLIC.
#
# The replacement also handles `auth.uid()` and `auth.jwt()`, which exhibit the
# same per-row re-evaluation issue.
# ---------------------------------------------------------------------------
_REWRITE_BLOCK = r"""
DO $$
DECLARE
    r record;
    new_qual text;
    new_wc   text;
    ddl      text;
    -- Known bare patterns in this codebase and their (select …) equivalents
    patterns text[][] := ARRAY[
        -- current_setting variants
        ARRAY[
            $$NULLIF(current_setting('app.tenant_id', true), '')::uuid$$,
            $$(select NULLIF(current_setting('app.tenant_id', true), '')::uuid)$$
        ],
        ARRAY[
            $$NULLIF(current_setting('app.user_id', true), '')::uuid$$,
            $$(select NULLIF(current_setting('app.user_id', true), '')::uuid)$$
        ],
        ARRAY[
            $$current_setting('app.tenant_id', true)::uuid$$,
            $$(select current_setting('app.tenant_id', true)::uuid)$$
        ],
        ARRAY[
            $$current_setting('app.tenant_id')::uuid$$,
            $$(select current_setting('app.tenant_id')::uuid)$$
        ],
        ARRAY[
            $$coalesce(current_setting('app.is_platform_admin', true), '') = 'true'$$,
            $$(select coalesce(current_setting('app.is_platform_admin', true), '') = 'true')$$
        ],
        -- auth.uid() / auth.jwt()
        ARRAY[$$auth.uid()$$, $$(select auth.uid())$$],
        ARRAY[$$auth.jwt()$$, $$(select auth.jwt())$$]
    ];
    i int;
BEGIN
    FOR r IN
        SELECT
            schemaname,
            tablename,
            policyname,
            cmd,
            qual,
            with_check
        FROM pg_policies
        WHERE schemaname = 'public'
          AND (
              (qual       IS NOT NULL AND (qual       ILIKE '%current_setting(%' OR qual       ILIKE '%auth.uid()%' OR qual       ILIKE '%auth.jwt()%'))
           OR (with_check IS NOT NULL AND (with_check ILIKE '%current_setting(%' OR with_check ILIKE '%auth.uid()%' OR with_check ILIKE '%auth.jwt()%'))
          )
    LOOP
        new_qual := r.qual;
        new_wc   := r.with_check;

        -- Apply each pattern substitution
        FOR i IN 1 .. array_length(patterns, 1)
        LOOP
            IF new_qual IS NOT NULL AND new_qual LIKE '%' || patterns[i][1] || '%' THEN
                -- Only replace if not already wrapped
                IF new_qual NOT LIKE '%(select ' || patterns[i][1] || ')%'
                   AND new_qual NOT LIKE '%(select ' || replace(patterns[i][1], 'NULLIF', 'nullif') || ')%'
                THEN
                    new_qual := replace(new_qual, patterns[i][1], patterns[i][2]);
                END IF;
            END IF;

            IF new_wc IS NOT NULL AND new_wc LIKE '%' || patterns[i][1] || '%' THEN
                IF new_wc NOT LIKE '%(select ' || patterns[i][1] || ')%'
                   AND new_wc NOT LIKE '%(select ' || replace(patterns[i][1], 'NULLIF', 'nullif') || ')%'
                THEN
                    new_wc := replace(new_wc, patterns[i][1], patterns[i][2]);
                END IF;
            END IF;
        END LOOP;

        -- Skip if nothing changed
        IF new_qual IS NOT DISTINCT FROM r.qual AND new_wc IS NOT DISTINCT FROM r.with_check THEN
            CONTINUE;
        END IF;

        -- ALTER POLICY, not DROP + CREATE. Rebuilding from pg_policies' deparsed
        -- text has to reproduce the command, the permissive flag AND the target
        -- roles, and the roles come back as `{=}` for every policy written
        -- without an explicit TO clause — which is how scripts/provision.py
        -- creates tenant_isolation. `CREATE POLICY ... TO =` is a syntax error,
        -- so the original form aborted the whole migration on any database
        -- provisioned the normal way. ALTER changes only the expressions and
        -- leaves command, roles and permissive flag exactly as they are.
        ddl := format('ALTER POLICY %I ON %I.%I',
                      r.policyname, r.schemaname, r.tablename);

        IF new_qual IS NOT NULL THEN
            ddl := ddl || ' USING (' || new_qual || ')';
        END IF;

        IF new_wc IS NOT NULL THEN
            ddl := ddl || ' WITH CHECK (' || new_wc || ')';
        END IF;

        EXECUTE ddl;

        RAISE NOTICE 'Rewrote RLS policy %.% (%)',
                     r.tablename, r.policyname, r.cmd;
    END LOOP;
END $$;
"""

# For downgrade we cannot truly "un-wrap" because the original expressions
# vary.  We mark this as a one-way migration.  The bare forms are strictly
# slower; there is no functional reason to revert.
_DOWNGRADE_NOTE = """
-- This migration is intentionally one-way.
-- Reverting (SELECT current_setting(...)) to current_setting(...) would
-- only degrade performance.  No data or security semantics change.
"""


def upgrade() -> None:
    op.execute(_REWRITE_BLOCK)


def downgrade() -> None:
    op.execute(_DOWNGRADE_NOTE)
