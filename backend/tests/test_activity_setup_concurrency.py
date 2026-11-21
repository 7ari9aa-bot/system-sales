"""Two taps on the setup's confirm button at the same moment apply it once, not twice.

Real concurrency on committed connections (the per-test ``db`` fixture is one rolled-back
connection and cannot show a race). Several racers each ask to complete the setup with the preset;
exactly one may win, the shop gets one category tree, and the preset is filled once.
"""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa

from app.core.activity_setup import (
    DONE,
    VERTICAL_PRESET,
    complete_setup,
    mark_not_started,
    read_state,
    reopen_setup,
    skip_setup,
)
from app.core.db import bind_tenant
from app.core.shop_type import APPAREL_STARTER_TREE
from tests.test_vertical_choice_concurrency import RACERS, committed_tenant  # noqa: F401

TREE = len(APPAREL_STARTER_TREE) + sum(len(v) for v in APPAREL_STARTER_TREE.values())
OWNER = {"settings:read", "settings:write"}


async def _go(factory, tenant_id, user_id):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            out = await complete_setup(
                s,
                tenant_id,
                vertical="apparel",
                apply_preset=True,
                user_id=user_id,
                permissions=OWNER,
            )
            await s.commit()
            return out
        except Exception as exc:  # noqa: BLE001 - the test reports whatever a racer hit
            await s.rollback()
            return exc


@pytest.mark.asyncio
async def test_racing_confirmations_apply_the_setup_exactly_once(committed_tenant) -> None:  # noqa: F811
    factory, tenant_id, user_id = committed_tenant
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        await mark_not_started(s, tenant_id)
        await s.commit()

    results = await asyncio.gather(*(_go(factory, tenant_id, user_id) for _ in range(RACERS)))

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    winners = [r for r in results if r["changed"]]
    assert len(winners) == 1, f"{len(winners)} racers applied the setup"
    assert winners[0]["preset_applied"] == VERTICAL_PRESET["apparel"]
    assert all(r["state"] == DONE for r in results)
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        assert await read_state(s, tenant_id) == DONE
        total = (
            await s.execute(
                sa.text("SELECT count(*) FROM categories WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert total == TREE


async def _reopen(factory, tenant_id, user_id):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            out = await reopen_setup(s, tenant_id, user_id=user_id)
            await s.commit()
            return out
        except Exception as exc:  # noqa: BLE001 - the test reports whatever a racer hit
            await s.rollback()
            return exc


ROUNDS = 12


@pytest.mark.asyncio
async def test_racing_reopens_change_the_marker_exactly_once(committed_tenant) -> None:  # noqa: F811
    # One round can pass by luck of timing even with no lock, so the race is run many times: the
    # marker is reset to skipped and RACERS sessions reopen it at once, and every round must have
    # exactly one winner.
    factory, tenant_id, user_id = committed_tenant
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        await mark_not_started(s, tenant_id)
        await s.commit()

    for round_no in range(ROUNDS):
        async with factory() as s:
            await bind_tenant(s, tenant_id)
            await skip_setup(s, tenant_id, user_id=user_id)
            await s.commit()
        results = await asyncio.gather(
            *(_reopen(factory, tenant_id, user_id) for _ in range(RACERS))
        )
        assert not [r for r in results if isinstance(r, Exception)], results
        winners = sum(1 for r in results if r["changed"])
        assert winners == 1, f"round {round_no}: {winners} racers reopened it"
