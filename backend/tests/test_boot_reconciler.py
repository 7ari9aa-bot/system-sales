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
        flags_result,      # orders flags
        policies_result,   # orders policies
        flags_result,      # customers flags
        policies_result,   # customers policies
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

    with patch("app.core.boot.inspect_tenant_rls_invariants", return_value=["leaky_table: RLS disabled"]):
        with pytest.raises(BootReconcilerError, match="leaky_table: RLS disabled"):
            await run_boot_reconciler(engine, fail_closed=True)


@pytest.mark.asyncio
async def test_run_boot_reconciler_warns_when_not_fail_closed() -> None:
    engine = MagicMock()
    conn_mock = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn_mock

    with patch("app.core.boot.inspect_tenant_rls_invariants", return_value=["leaky_table: RLS disabled"]):
        violations = await run_boot_reconciler(engine, fail_closed=False)
        assert violations == ["leaky_table: RLS disabled"]
