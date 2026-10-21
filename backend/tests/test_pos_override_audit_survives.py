"""A refused PIN must leave a trace even though the request that carried it rolls back.

The per-test ``db`` fixture is one rolled-back connection, so it can never show this: the refusal
row written on the request's own transaction vanishes with that transaction's rollback, and the
in-transaction test still sees it. This module commits a throw-away tenant and rolls back for real.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError
from app.modules.pos.override import ManagerPinService
from tests.test_pos_returns_concurrency import admin_url, committed_tenant  # noqa: F401, I001


async def _audit_actions(factory, tenant_id) -> list[str]:
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        rows = await s.execute(
            sa.text(
                "SELECT action FROM audit_logs WHERE tenant_id = :t "
                "AND action LIKE 'pos.override.%' ORDER BY created_at"
            ),
            {"t": tenant_id},
        )
        return [r[0] for r in rows]


async def _user_id(factory, tenant_id):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        return (
            await s.execute(
                sa.text("SELECT user_id FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()


async def test_a_refused_pin_is_recorded_after_the_request_rolls_back(
    committed_tenant,  # noqa: F811
    monkeypatch,
) -> None:
    factory, tenant_id = committed_tenant
    user_id = await _user_id(factory, tenant_id)

    # The lockout counter lives in Redis; this test is about the audit row, not the counter.
    from app.core import auth_lockout
    from app.modules.pos import override

    class _Status:
        locked = False
        retry_after_seconds = 0

    async def _check(*_a, **_k):
        return _Status()

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(auth_lockout, "check", _check)
    monkeypatch.setattr(auth_lockout, "record_failure", _noop)
    monkeypatch.setattr(override, "get_redis", lambda: object())

    # What the router does: one transaction for the request, a refusal raised inside it, rollback.
    async with factory() as request_tx:
        await bind_tenant(request_tx, tenant_id)
        with pytest.raises(PermissionDeniedError):
            await ManagerPinService.approve(
                request_tx,
                tenant_id,
                cashier_id=user_id,
                manager_id=uuid.uuid4(),  # nobody: the answer is "refused"
                pin="0000",
                operation="sell",
            )
        await request_tx.rollback()

    assert await _audit_actions(factory, tenant_id) == ["pos.override.denied"]
