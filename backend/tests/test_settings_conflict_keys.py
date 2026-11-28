"""The 409 names every key that moved, not just the first one the write loop reaches.

A save that touches five keys and lost two of them used to raise on the first stale key: the
owner fixed that one, reloaded, saved again, and got a second 409 for the other. The banner
also had nothing to name, so it blamed the whole form.
"""

from __future__ import annotations

import uuid

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration
from app.core.db import bind_tenant
from app.core.errors import ConflictError
from app.platform.identity.services.auth import AuthService
from app.platform.settings.registry import Scope
from app.platform.settings.service import SettingsService


async def _tenant(db):
    _, tenant = await AuthService.register(
        db,
        tenant_name="Conflict Co",
        tenant_slug=f"conflict-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="conflict-pass-1",
        full_name="Conflict Owner",
    )
    await bind_tenant(db, tenant.id)
    return tenant


@pytest.mark.asyncio
async def test_a_bulk_save_names_every_stale_key(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)
    keys = ["pos.return_max_days", "catalog.max_variants_per_product"]

    for key in keys:
        await svc.set(key, 5, scope=Scope.TENANT)
    seen = await svc._latest_history_ids(keys, Scope.TENANT.value, None)
    assert all(seen.get(k) for k in keys), "both keys must have a history row to conflict on"

    # Someone else moves both keys after this caller read them.
    await svc.set(keys[0], 6, scope=Scope.TENANT)
    await svc.set(keys[1], 7, scope=Scope.TENANT)

    with pytest.raises(ConflictError) as caught:
        await svc.bulk_set(
            {keys[0]: 8, keys[1]: 9},
            scope=Scope.TENANT,
            expected_history_ids=seen,
        )

    assert caught.value.details["conflicting_keys"] == sorted(keys)
    assert all(k in caught.value.message for k in keys)


@pytest.mark.asyncio
async def test_a_key_that_did_not_move_is_not_blamed(db) -> None:
    tenant = await _tenant(db)
    svc = SettingsService(db, tenant.id)
    keys = ["pos.return_max_days", "catalog.max_variants_per_product"]
    for key in keys:
        await svc.set(key, 5, scope=Scope.TENANT)
    seen = await svc._latest_history_ids(keys, Scope.TENANT.value, None)

    await svc.set(keys[0], 6, scope=Scope.TENANT)  # only the first one moves

    with pytest.raises(ConflictError) as caught:
        await svc.bulk_set(
            {keys[0]: 8, keys[1]: 9},
            scope=Scope.TENANT,
            expected_history_ids=seen,
        )

    assert caught.value.details["conflicting_keys"] == [keys[0]]
