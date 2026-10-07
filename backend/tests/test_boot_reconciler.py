"""Tests for Invariant 13 Boot Reconciler (app/core/boot.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.boot import (
    BootReconcilerError,
    inspect_tenant_rls_invariants,
    run_boot_reconciler,
)


@pytest.mark.asyncio
async def test_inspect_tenant_rls_invariants_clean() -> None:
    session = AsyncMock()

    # 1. tables query
    tables_result = MagicMock()
    tables_result.fetchall.return_value = [("orders",), ("customers",), ("outbox_events",)]

    # 2. flags queries: relrowsecurity=True, relforcerowsecurity=True
    flags_result = MagicMock()
    flags_result.one_or_none.return_value = (True, True)

    # 3. policies queries: has tenant_isolation
    policies_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = ["tenant_isolation"]
    policies_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        tables_result,
        flags_result,  # orders flags
        policies_result,  # orders policies
        flags_result,  # customers flags
        policies_result,  # customers policies
    ]

    violations = await inspect_tenant_rls_invariants(session)
    assert violations == []


@pytest.mark.asyncio
async def test_inspect_tenant_rls_invariants_detects_unforced_and_missing_policy() -> None:
    session = AsyncMock()

    # Table with missing force and missing policy
    tables_result = MagicMock()
    tables_result.fetchall.return_value = [("bad_table",)]

    flags_result = MagicMock()
    flags_result.one_or_none.return_value = (True, False)  # Not forced!

    policies_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = ["wrong_policy"]  # Missing tenant_isolation!
    policies_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        tables_result,
        flags_result,
        policies_result,
    ]

    violations = await inspect_tenant_rls_invariants(session)
    assert len(violations) == 2
    assert any("RLS is NOT forced" in v for v in violations)
    assert any("missing canonical 'tenant_isolation' policy" in v for v in violations)


@pytest.mark.asyncio
async def test_run_boot_reconciler_fails_closed_in_secure_environment() -> None:
    engine = MagicMock()
    conn_mock = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn_mock

    with (
        patch(
            "app.core.boot.inspect_tenant_rls_invariants",
            return_value=["leaky_table: RLS disabled"],
        ),
        patch(
            # The role-side check probes the connected role through the session;
            # stubbed here so this test pins ONLY the table-side violations.
            "app.core.boot.inspect_app_role_bypass_rls",
            return_value=None,
        ),
    ):
        with pytest.raises(BootReconcilerError, match="leaky_table: RLS disabled"):
            await run_boot_reconciler(engine, fail_closed=True)


@pytest.mark.asyncio
async def test_run_boot_reconciler_warns_when_not_fail_closed() -> None:
    engine = MagicMock()
    conn_mock = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn_mock

    with (
        patch(
            "app.core.boot.inspect_tenant_rls_invariants",
            return_value=["leaky_table: RLS disabled"],
        ),
        patch("app.core.boot.inspect_app_role_bypass_rls", return_value=None),
    ):
        violations = await run_boot_reconciler(engine, fail_closed=False)
        assert violations == ["leaky_table: RLS disabled"]


@pytest.mark.asyncio
async def test_run_boot_reconciler_refuses_when_the_connected_role_bypasses_rls() -> None:
    """The role-side half of Invariant 13: RLS FORCED on every table means
    nothing if the CONNECTED role carries BYPASSRLS — none of the policies
    bind it. A secure environment refuses to boot."""
    engine = MagicMock()
    conn_mock = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn_mock

    with (
        patch(
            "app.core.boot.inspect_tenant_rls_invariants",
            return_value=[],
        ),
        patch(
            "app.core.boot.inspect_app_role_bypass_rls",
            return_value=(
                "connected role 'sales_admin' has BYPASSRLS — row-level security cannot bind it"
            ),
        ),
    ):
        with pytest.raises(BootReconcilerError, match="BYPASSRLS"):
            await run_boot_reconciler(engine, fail_closed=True)


@pytest.mark.asyncio
async def test_run_boot_reconciler_warns_on_role_bypass_outside_secure_environments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Local/test roles are usually superusers (BYPASSRLS by construction):
    logged loudly, never fatal."""
    engine = MagicMock()
    conn_mock = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn_mock

    with (
        patch(
            "app.core.boot.inspect_tenant_rls_invariants",
            return_value=[],
        ),
        patch(
            "app.core.boot.inspect_app_role_bypass_rls",
            return_value=(
                "connected role 'postgres' has BYPASSRLS — row-level security cannot bind it"
            ),
        ),
    ):
        violations = await run_boot_reconciler(engine, fail_closed=False)

    assert violations == [], "a dev-environment role violation must not fail the boot"
    assert any("app_role_bypassrls" in r.message for r in caplog.records)
