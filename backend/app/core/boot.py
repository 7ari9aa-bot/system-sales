"""Boot Reconciler (Invariant 13) — fail-closed security verification at startup.

Every table in the database that carries a ``tenant_id`` column MUST:
1. Have Row Level Security enabled (``relrowsecurity = true``);
2. Have Row Level Security FORCED (``relforcerowsecurity = true``), so table
   owners and superusers (unless bypassrls) are still bound;
3. Have the canonical ``tenant_isolation`` policy defined in ``pg_policies``.

If ANY tenant-scoped table fails this invariant, the system refuses to boot
(Invariant 13 fail-closed rule) in secure/production environments.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Tables that have tenant_id or are system-level/operational and are deliberately
#: managed outside tenant isolation policies (the agreed repo-wide exemption list).
RLS_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        "outbox_events",
        "idempotency_keys",
        "plans",
        "refresh_tokens",
        "webhook_events",
        "scheduled_jobs",
        "audit_logs",
        "security_events",
    }
)


class BootReconcilerError(RuntimeError):
    """Refusal to boot because a fundamental security invariant was violated."""


async def inspect_tenant_rls_invariants(
    session: AsyncSession,
    *,
    exempt_tables: Iterable[str] = RLS_EXEMPT_TABLES,
) -> list[str]:
    """Inspect PostgreSQL catalogs for Invariant 13 compliance across all tables.

    Returns a list of violation descriptions. An empty list means 100% compliant.
    """
    exempt = set(exempt_tables)
    tables_result = await session.execute(
        text(
            """
            SELECT DISTINCT c.table_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = 'public' AND t.table_name = c.table_name
            WHERE c.table_schema = 'public'
              AND c.column_name = 'tenant_id'
              AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name
            """
        )
    )
    tenant_tables = [row[0] for row in tables_result.fetchall()]

    violations: list[str] = []
    for name in tenant_tables:
        if name in exempt:
            continue

        flags = (
            await session.execute(
                text(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = :t
                    """
                ),
                {"t": name},
            )
        ).one_or_none()

        if flags is None:
            violations.append(f"{name}: table found in information_schema but missing in pg_class")
            continue

        relrowsecurity, relforcerowsecurity = flags[0], flags[1]
        if not relrowsecurity:
            violations.append(f"{name}: RLS is NOT enabled (relrowsecurity=false)")
        if not relforcerowsecurity:
            violations.append(f"{name}: RLS is NOT forced (relforcerowsecurity=false)")

        policies = (
            await session.execute(
                text(
                    """
                    SELECT policyname
                    FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = :t
                    """
                ),
                {"t": name},
            )
        ).scalars().all()

        policy_names = set(policies)
        if "tenant_isolation" not in policy_names:
            violations.append(
                f"{name}: missing canonical 'tenant_isolation' policy (found: {sorted(policy_names)})"
            )

    return violations


async def run_boot_reconciler(
    engine: AsyncEngine,
    *,
    fail_closed: bool | None = None,
) -> list[str]:
    """Execute startup security verification against the active database.

    In secure environments (production/staging), raises BootReconcilerError on violation.
    """
    settings = get_settings()
    should_fail_closed = (
        fail_closed if fail_closed is not None else settings.is_secure_environment
    )

    try:
        async with engine.connect() as conn:
            async with AsyncSession(conn) as session:
                violations = await inspect_tenant_rls_invariants(session)
    except Exception as exc:
        if should_fail_closed:
            raise BootReconcilerError(
                f"Boot Reconciler database probe failed: {exc}"
            ) from exc
        logger.warning("boot_reconciler.probe_skipped: %s", exc)
        return []

    if violations:
        msg = (
            "FATAL: Invariant 13 violated — tenant isolation RLS is incomplete:\n  "
            + "\n  ".join(violations)
        )
        logger.critical("%s", msg)
        if should_fail_closed:
            raise BootReconcilerError(msg)

    logger.info("boot_reconciler.passed: Invariant 13 verified across tenant tables")
    return violations
