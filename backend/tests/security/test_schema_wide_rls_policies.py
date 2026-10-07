"""SEC-1.3: RLS FORCE + the canonical policy, proven against the SCHEMA, not the ORM.

`test_every_tenant_scoped_model_table_has_a_policy` closes the loop from the
model side — but the voice/phase-9 tables have no ORM model at all, so a model
driven sweep cannot see them, and phase9 shipped them a permissive
``<table>_tenant_isolation`` policy whose bare ``current_setting`` qual RAISES
on an unbound session, without FORCE. d8a1b2c3d4e5's dynamic sweep repairs
every such table on a fresh database; THIS gate makes the property itself the
invariant, so the next table that arrives through raw SQL — no model, no
sweep remember-me — fails CI on the same run that created it.

CI-only: needs `DATABASE_URL_APP_ADMIN`, skips locally. Exempt list is the
same one b2c3d4e5f6a7 / d8a1b2c3d4e5 / provision.py agree on.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

EXEMPT = {
    "outbox_events",
    "idempotency_keys",
    "plans",
    "refresh_tokens",
    "webhook_events",
    "scheduled_jobs",
    "audit_logs",
    "security_events",
}


@pytest.mark.asyncio
async def test_every_schema_table_with_tenant_id_is_force_rls_with_canonical_policy(db):
    tables = (
        await db.execute(
            text(
                """
                SELECT DISTINCT c.table_name
                FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_schema = 'public' AND t.table_name = c.table_name
                WHERE c.table_schema = 'public'
                  AND c.column_name = 'tenant_id'
                  AND t.table_type = 'BASE TABLE'
                """
            )
        )
    ).scalars()

    offenders = []
    for name in sorted(set(tables) - EXEMPT):
        flags = (
            await db.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = :t"
                ),
                {"t": name},
            )
        ).one_or_none()
        if flags is None:
            offenders.append(f"{name}: table vanished mid-run?")
            continue
        if not (flags.relrowsecurity and flags.relforcerowsecurity):
            offenders.append(
                f"{name}: RLS enabled={flags.relrowsecurity} forced={flags.relforcerowsecurity}"
            )

        policies = (
            await db.execute(
                text(
                    "SELECT policyname, cmd, permissive FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = :t"
                ),
                {"t": name},
            )
        ).all()
        names = {p.policyname for p in policies}
        if "tenant_isolation" not in names:
            offenders.append(f"{name}: no canonical tenant_isolation policy (has {sorted(names)})")
        elif names - {"tenant_isolation"}:
            offenders.append(
                f"{name}: legacy permissive policies survive beside the canonical "
                f"one and OR-open the table: {sorted(names - {'tenant_isolation'})}"
            )

    assert not offenders, (
        "every tenant_id table must be FORCE RLS with exactly the canonical "
        "tenant_isolation policy and no legacy permissive policy beside it — "
        "see d8a1b2c3d4e5's sweep for the repair idiom:\n  " + "\n  ".join(offenders)
    )
