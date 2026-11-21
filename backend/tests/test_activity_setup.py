"""First-run activity setup: asked once, never forced, never overwrites what the owner built.

A signup starts ``not_started``; every shop that existed before has no row and reads ``done``. The
owner completes (a vertical, and the vertical's preset only when asked) or skips. A second call is
a no-op, and the preset fills only switches the owner never touched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.activity_setup import (
    DONE,
    NOT_STARTED,
    SKIPPED,
    VERTICAL_PRESET,
    complete_setup,
    mark_not_started,
    read_state,
    reopen_setup,
    skip_setup,
)
from app.core.errors import ValidationError
from app.modules.catalog.models import Category
from app.modules.settings.presets import PRESETS
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

OWNER = {"settings:read", "settings:write"}
CASHIER = {"orders:read", "orders:write"}
PRESET = VERTICAL_PRESET["apparel"]


async def _vertical(db, tid):
    return (await SettingsService(db, tid).resolve("business.vertical")).value


async def _cats(db, tid):
    return list((await db.execute(select(Category).where(Category.tenant_id == tid))).scalars())


async def _complete(db, ctx, vertical="apparel", apply_preset=False):
    return await complete_setup(
        db,
        ctx.tenant_id,
        vertical=vertical,
        apply_preset=apply_preset,
        user_id=ctx.user.id,
        permissions=OWNER,
    )


# ── the state ─────────────────────────────────────────────────────────────────────────────────


async def test_a_shop_that_existed_before_reads_done(db, tenant_ctx) -> None:
    # No row was ever written for it: this is every shop running today.
    assert await read_state(db, tenant_ctx.tenant_id) == DONE


async def test_a_new_signup_reads_not_started(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    assert await read_state(db, tenant_ctx.tenant_id) == NOT_STARTED


async def test_marking_one_shop_leaves_another_done(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    assert await read_state(db, uuid.uuid4()) == DONE


# ── completing ────────────────────────────────────────────────────────────────────────────────


async def test_completing_sets_the_vertical_and_marks_done(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    out = await _complete(db, tenant_ctx)
    assert out["changed"] is True and out["state"] == DONE
    assert out["vertical"] == "apparel"
    assert await _vertical(db, tid) == "apparel"
    assert await read_state(db, tid) == DONE
    assert len(await _cats(db, tid)) == out["categories_created"] > 0


async def test_the_preset_is_applied_only_when_the_owner_asks_for_it(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    out = await _complete(db, tenant_ctx, apply_preset=False)
    assert out["preset_applied"] is None and out["settings_filled"] == 0
    s = SettingsService(db, tid)
    # pos.take_payments is a key of the preset; without the owner's yes it stays the default.
    assert (await s.resolve("pos.take_payments")).is_default


async def test_asking_for_the_preset_fills_its_values(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    out = await _complete(db, tenant_ctx, apply_preset=True)
    assert out["preset_applied"] == PRESET
    assert out["settings_filled"] > 0
    s = SettingsService(db, tid)
    assert (await s.resolve("pos.take_payments")).value is True
    assert (await s.resolve("pos.allow_sale_on_account")).value is False


async def test_the_preset_never_overwrites_a_choice_the_owner_already_made(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    # The owner set these by hand before the setup ever ran.
    await s.set("print.copies", 3, user_id=tenant_ctx.user.id)
    await s.set("pos.allow_hold_cart", False, user_id=tenant_ctx.user.id)
    assert PRESETS[PRESET]["print.copies"] == 1 and PRESETS[PRESET]["pos.allow_hold_cart"] is True
    await mark_not_started(db, tid)
    await _complete(db, tenant_ctx, apply_preset=True)
    assert (await s.resolve("print.copies")).value == 3
    assert (await s.resolve("pos.allow_hold_cart")).value is False
    # and the keys the owner never touched did get the preset's value
    assert (await s.resolve("pos.take_payments")).value is True


async def test_general_offers_no_preset_even_when_asked(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    out = await _complete(db, tenant_ctx, vertical="general", apply_preset=True)
    assert out["preset_applied"] is None and out["settings_filled"] == 0
    assert await _vertical(db, tid) == "general"
    assert await _cats(db, tid) == []


# ── twice is the same as once ─────────────────────────────────────────────────────────────────


async def test_a_second_complete_changes_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    first = await _complete(db, tenant_ctx, apply_preset=True)
    n = len(await _cats(db, tid))
    s = SettingsService(db, tid)
    # the owner builds on top of it
    await s.set("print.copies", 4, user_id=tenant_ctx.user.id)
    again = await _complete(db, tenant_ctx, apply_preset=True)
    assert first["changed"] is True
    assert again == {"state": DONE, "changed": False, "vertical": None, "preset_applied": None}
    assert len(await _cats(db, tid)) == n
    assert (await s.resolve("print.copies")).value == 4


async def test_completing_a_shop_that_was_never_marked_does_nothing(db, tenant_ctx) -> None:
    # An existing shop (state done by default) calling complete must not be re-planted or re-set.
    tid = tenant_ctx.tenant_id
    out = await _complete(db, tenant_ctx, apply_preset=True)
    assert out["changed"] is False and out["state"] == DONE
    assert await _cats(db, tid) == []
    assert (await SettingsService(db, tid).resolve("pos.take_payments")).is_default


# (two real racing sessions: tests/test_activity_setup_concurrency.py)


# ── skipping ──────────────────────────────────────────────────────────────────────────────────


async def test_skipping_marks_it_and_touches_nothing_else(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    out = await skip_setup(db, tid, user_id=tenant_ctx.user.id)
    assert out == {"state": SKIPPED, "changed": True}
    assert await read_state(db, tid) == SKIPPED
    assert await _cats(db, tid) == []
    assert await _vertical(db, tid) == "general"


async def test_skipping_twice_or_after_completing_changes_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    await _complete(db, tenant_ctx)
    out = await skip_setup(db, tid, user_id=tenant_ctx.user.id)
    assert out == {"state": DONE, "changed": False}
    assert await read_state(db, tid) == DONE


async def test_a_skipped_shop_is_not_set_up_by_a_later_complete(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    await skip_setup(db, tid, user_id=tenant_ctx.user.id)
    out = await _complete(db, tenant_ctx, apply_preset=True)
    assert out["changed"] is False and out["state"] == SKIPPED
    assert await _cats(db, tid) == []


# ── what may be chosen ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "vertical", ["pharmacy", "restaurant", "electronics", "wholesale", "x", ""]
)
async def test_a_sector_that_changes_nothing_is_refused_and_leaves_the_state(
    db, tenant_ctx, vertical
) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    with pytest.raises(ValidationError):
        await _complete(db, tenant_ctx, vertical=vertical)
    assert await read_state(db, tid) == NOT_STARTED
    assert await _vertical(db, tid) == "general"


# ── the routes ────────────────────────────────────────────────────────────────────────────────


async def _call(db, ctx, method, path, *, perms, body=None):
    from tests.test_pos_close_variance_discipline import _call as call

    return await call(db, ctx, method, path, perms=perms, body=body)


BASE = "/api/v1/activity-setup"


async def test_the_owner_of_a_new_shop_is_told_to_show_the_setup(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    r = await _call(db, tenant_ctx, "GET", BASE, perms=OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == NOT_STARTED and body["needs_setup"] is True
    assert set(body["choices"]) == {"general", "apparel"}
    assert body["presets"] == {"apparel": PRESET}
    assert body["preset_keys"]["apparel"] == sorted(PRESETS[PRESET])


async def test_a_cashier_is_never_told_to_show_it_but_can_read_the_state(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    r = await _call(db, tenant_ctx, "GET", BASE, perms=CASHIER)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == NOT_STARTED and r.json()["needs_setup"] is False


async def test_an_existing_owner_and_a_skipped_owner_are_never_told_to_show_it(
    db, tenant_ctx
) -> None:
    r = await _call(db, tenant_ctx, "GET", BASE, perms=OWNER)
    assert r.json()["state"] == DONE and r.json()["needs_setup"] is False
    await mark_not_started(db, tenant_ctx.tenant_id)
    await skip_setup(db, tenant_ctx.tenant_id, user_id=tenant_ctx.user.id)
    r = await _call(db, tenant_ctx, "GET", BASE, perms=OWNER)
    assert r.json()["state"] == SKIPPED and r.json()["needs_setup"] is False


async def test_a_cashier_cannot_complete_or_skip(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    done = await _call(
        db, tenant_ctx, "POST", f"{BASE}/complete", perms=CASHIER, body={"vertical": "apparel"}
    )
    skip = await _call(db, tenant_ctx, "POST", f"{BASE}/skip", perms=CASHIER)
    assert done.status_code == 403 and skip.status_code == 403
    assert await read_state(db, tenant_ctx.tenant_id) == NOT_STARTED


async def test_the_owner_completes_through_the_route_and_a_repeat_changes_nothing(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    body = {"vertical": "apparel", "apply_preset": True}
    first = await _call(db, tenant_ctx, "POST", f"{BASE}/complete", perms=OWNER, body=body)
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True and first.json()["preset_applied"] == PRESET
    second = await _call(db, tenant_ctx, "POST", f"{BASE}/complete", perms=OWNER, body=body)
    assert second.status_code == 200 and second.json()["changed"] is False
    state = (await _call(db, tenant_ctx, "GET", BASE, perms=OWNER)).json()
    assert state["state"] == DONE and state["needs_setup"] is False


async def test_the_route_refuses_a_sector_and_a_missing_vertical(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    bad = await _call(
        db, tenant_ctx, "POST", f"{BASE}/complete", perms=OWNER, body={"vertical": "pharmacy"}
    )
    assert bad.status_code == 400, bad.text
    missing = await _call(db, tenant_ctx, "POST", f"{BASE}/complete", perms=OWNER, body={})
    assert missing.status_code == 422
    assert await read_state(db, tenant_ctx.tenant_id) == NOT_STARTED


async def test_the_owner_skips_through_the_route(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    r = await _call(db, tenant_ctx, "POST", f"{BASE}/skip", perms=OWNER)
    assert r.status_code == 200 and r.json() == {"state": SKIPPED, "changed": True}


# ── the confirmation is explicit, and writing needs write ─────────────────────────────────────

READER = {"settings:read"}


async def test_the_route_applies_no_preset_unless_the_owner_sends_the_flag(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    # The body names only the vertical: the owner never said yes to the preset.
    r = await _call(
        db, tenant_ctx, "POST", f"{BASE}/complete", perms=OWNER, body={"vertical": "apparel"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["preset_applied"] is None and r.json()["settings_filled"] == 0
    assert (await SettingsService(db, tid).resolve("pos.take_payments")).is_default


async def test_reading_the_settings_is_not_enough_to_complete_or_skip(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    done = await _call(
        db, tenant_ctx, "POST", f"{BASE}/complete", perms=READER, body={"vertical": "apparel"}
    )
    skip = await _call(db, tenant_ctx, "POST", f"{BASE}/skip", perms=READER)
    assert done.status_code == 403 and skip.status_code == 403
    assert await read_state(db, tenant_ctx.tenant_id) == NOT_STARTED
    assert await _vertical(db, tenant_ctx.tenant_id) == "general"


async def test_a_refused_sector_is_refused_before_anything_is_touched(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    with pytest.raises(ValidationError, match="vertical must be one of"):
        await _complete(db, tenant_ctx, vertical="pharmacy", apply_preset=True)
    # not even the preset's keys were written
    assert (await SettingsService(db, tid).resolve("pos.take_payments")).is_default
    assert await _cats(db, tid) == []


# ── reopening ─────────────────────────────────────────────────────────────────────────────────


async def test_a_finished_or_skipped_shop_can_be_reopened(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    await _complete(db, tenant_ctx)
    assert await read_state(db, tid) == DONE
    out = await reopen_setup(db, tid, user_id=tenant_ctx.user.id)
    assert out == {"state": NOT_STARTED, "changed": True}
    assert await read_state(db, tid) == NOT_STARTED
    await skip_setup(db, tid, user_id=tenant_ctx.user.id)
    assert await read_state(db, tid) == SKIPPED
    assert (await reopen_setup(db, tid, user_id=tenant_ctx.user.id))["changed"] is True


async def test_reopening_a_shop_that_is_already_waiting_changes_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    assert await reopen_setup(db, tid, user_id=tenant_ctx.user.id) == {
        "state": NOT_STARTED,
        "changed": False,
    }


async def test_reopening_an_existing_shop_asks_it_again_and_touches_nothing_else(
    db, tenant_ctx
) -> None:
    # A shop from before the setup existed reads done; the owner may still reopen it.
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    await s.set("print.copies", 5, user_id=tenant_ctx.user.id)
    await reopen_setup(db, tid, user_id=tenant_ctx.user.id)
    assert await read_state(db, tid) == NOT_STARTED
    assert (await s.resolve("print.copies")).value == 5
    assert await _cats(db, tid) == []


async def test_reopening_then_confirming_never_overwrites_what_the_owner_built_since(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    s = SettingsService(db, tid)
    await mark_not_started(db, tid)
    await _complete(db, tenant_ctx, apply_preset=True)
    # The owner then makes the shop their own...
    await s.set("print.copies", 4, user_id=tenant_ctx.user.id)
    await s.set("pos.take_payments", False, user_id=tenant_ctx.user.id)
    n = len(await _cats(db, tid))
    # ...reopens the setup and confirms the clothing preset again.
    await reopen_setup(db, tid, user_id=tenant_ctx.user.id)
    out = await _complete(db, tenant_ctx, apply_preset=True)
    assert out["changed"] is True and out["preset_applied"] == PRESET
    assert (await s.resolve("print.copies")).value == 4
    assert (await s.resolve("pos.take_payments")).value is False
    assert len(await _cats(db, tid)) == n


async def test_the_route_reopens_for_the_owner_only(db, tenant_ctx) -> None:
    await mark_not_started(db, tenant_ctx.tenant_id)
    await skip_setup(db, tenant_ctx.tenant_id, user_id=tenant_ctx.user.id)
    denied = await _call(db, tenant_ctx, "POST", f"{BASE}/reopen", perms=CASHIER)
    reader = await _call(db, tenant_ctx, "POST", f"{BASE}/reopen", perms=READER)
    assert denied.status_code == 403 and reader.status_code == 403
    assert await read_state(db, tenant_ctx.tenant_id) == SKIPPED
    ok = await _call(db, tenant_ctx, "POST", f"{BASE}/reopen", perms=OWNER)
    assert ok.status_code == 200 and ok.json() == {"state": NOT_STARTED, "changed": True}
    state = (await _call(db, tenant_ctx, "GET", BASE, perms=OWNER)).json()
    assert state["needs_setup"] is True


async def test_the_history_names_who_reopened_it_through_the_route(db, tenant_ctx) -> None:
    from sqlalchemy import text

    tid = tenant_ctx.tenant_id
    await mark_not_started(db, tid)
    await skip_setup(db, tid, user_id=tenant_ctx.user.id)
    r = await _call(db, tenant_ctx, "POST", f"{BASE}/reopen", perms=OWNER)
    assert r.status_code == 200, r.text
    who = (
        await db.execute(
            text(
                "select changed_by from tenant_settings_history where tenant_id = :t"
                " and key = 'business.setup_state' and new_value::text like '%not_started%'"
                " order by created_at desc limit 1"
            ),
            {"t": tid},
        )
    ).scalar()
    assert who == tenant_ctx.user.id
