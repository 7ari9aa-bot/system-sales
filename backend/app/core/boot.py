"""Boot Reconciler (Invariant 13) — fail-closed security verification at startup.

Every table in the database that carries a ``tenant_id`` column MUST:
1. Have Row Level Security enabled (``relrowsecurity = true``);
2. Have Row Level Security FORCED (``relforcerowsecurity = true``), so table
   owners and superusers (unless bypassrls) are still bound;
3. Have the canonical ``tenant_isolation`` policy defined in ``pg_policies``.

And the role side: the CONNECTED database role must NOT carry BYPASSRLS —
otherwise none of the above binds the app (checked by
``inspect_app_role_bypass_rls``).

If ANY tenant-scoped table fails this invariant, or the connected role
bypasses RLS, the system refuses to boot (Invariant 13 fail-closed rule) in
secure/production environments. Outside them (local/test, where the developer
role is usually the superuser) violations are logged, not fatal.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

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
        "password_reset_tokens",
        "webhook_events",
        "scheduled_jobs",
        "audit_logs",
        "security_events",
    }
)


class BootReconcilerError(RuntimeError):
    """Refusal to boot because a fundamental security invariant was violated."""


async def inspect_app_role_bypass_rls(session: AsyncSession) -> str | None:
    """Check the CONNECTED role for BYPASSRLS (Invariant 13's role-side half).

    Every table-level guarantee above binds sessions through the app role —
    which is exactly why the role itself must not carry BYPASSRLS: with it,
    ``sales_app`` reads and writes EVERY tenant's rows no matter what the
    policies say, and Invariant 13 becomes decoration. Returns a violation
    description, or None when the connected role is clean.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT r.rolname, r.rolbypassrls
                FROM pg_roles r
                WHERE r.rolname = current_user
                """
            )
        )
    ).one_or_none()
    if row is None:  # pragma: no cover — current_user is always in pg_roles
        return "connected role not found in pg_roles"
    rolname, rolbypassrls = row[0], row[1]
    if rolbypassrls:
        return (
            f"connected role {rolname!r} has BYPASSRLS — row-level security "
            "cannot bind it, so tenant isolation is unenforceable for the app"
        )
    return None


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

        policies_list = (
            (
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
            )
            .scalars()
            .all()
        )

        policy_names = set(policies_list)
        if "tenant_isolation" not in policy_names:
            found_str = sorted(policy_names)
            violations.append(
                f"{name}: missing canonical 'tenant_isolation' policy (found: {found_str})"
            )

    return violations


async def run_boot_reconciler(
    engine: AsyncEngine | None = None,
    *,
    fail_closed: bool | None = None,
) -> list[str]:
    """Execute startup security verification against the active database.

    In secure environments (production/staging), raises BootReconcilerError on violation.
    """
    settings = get_settings()
    should_fail_closed = fail_closed if fail_closed is not None else settings.is_secure_environment

    owns_engine = engine is None
    if engine is None:
        # Dedicated throwaway engine, disposed below: a probe on the
        # process-wide engine leaves pooled connections bound to THIS loop,
        # and the next loop's pool_pre_ping dies on an asyncpg future owned
        # by a dead loop. One probe, one engine, no shared-pool residue.
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )

    try:
        async with engine.connect() as conn:
            async with AsyncSession(conn) as session:
                violations = await inspect_tenant_rls_invariants(session)
                # The role-side half of the invariant: RLS FORCED on every
                # table means nothing if the connected role bypasses it. In
                # local/test the developer role (often postgres, superuser,
                # BYPASSRLS by construction) is expected — logged, not fatal.
                role_violation = await inspect_app_role_bypass_rls(session)
    except Exception as exc:
        if should_fail_closed:
            raise BootReconcilerError(f"Boot Reconciler database probe failed: {exc}") from exc
        logger.warning("boot_reconciler.probe_skipped: %s", exc)
        return []
    finally:
        if owns_engine:
            await engine.dispose()

    if role_violation:
        if should_fail_closed:
            violations.insert(0, role_violation)
        else:
            logger.warning(
                "boot_reconciler.app_role_bypassrls (non-fatal outside secure environments): %s",
                role_violation,
            )

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
