"""Who may open the profit, sell-through and dead-stock reports and reprice a season.

A shop decides whether its managers see what it paid for stock and what it earns. The setting
``reports.managers_see_profit`` is the owner's. It defaults to ON (every shop behaved this way
before the setting existed), and a cashier is refused whatever it says. The roles under test
are the real ones from ``scripts/provision.py``, not hand-written permission sets.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from app.modules.settings.service import SettingsService

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEY = "reports.managers_see_profit"


def _roles() -> dict[str, set[str]]:
    spec = importlib.util.spec_from_file_location("provision", ROOT / "scripts" / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {role: set(perms) for role, perms in module.ROLE_MATRIX.items()}


ROLES = _roles()

GETS = (
    "/api/v1/reports/dead-stock",
    "/api/v1/reports/sell-through?start=2026-01-01&end=2026-12-31",
    "/api/v1/reports/profit?start=2026-01-01&end=2026-12-31",
)
POSTS = (
    ("/api/v1/catalog/season-markdown/preview", {"season": "SS26", "percent": "20"}),
    ("/api/v1/catalog/season-markdown/apply", {"season": "SS26", "percent": "20", "token": "x"}),
)


async def _status(db, tenant_ctx, role: str, method: str, path: str, body=None) -> int:
    from tests.test_pos_close_variance_discipline import _call

    return (await _call(db, tenant_ctx, method, path, perms=ROLES[role], body=body)).status_code


async def _all(db, tenant_ctx, role: str) -> dict[str, int]:
    out = {}
    for path in GETS:
        out[path] = await _status(db, tenant_ctx, role, "GET", path)
    for path, body in POSTS:
        out[path] = await _status(db, tenant_ctx, role, "POST", path, body)
    return out


def test_the_real_roles_are_what_this_test_assumes() -> None:
    assert "pos:override" in ROLES["owner"] and "settings:write" in ROLES["owner"]
    assert "pos:override" in ROLES["manager"] and "settings:write" not in ROLES["manager"]
    assert "pos:override" not in ROLES["staff"]


def test_the_setting_is_on_by_default_and_the_owner_can_turn_it_off() -> None:
    from app.modules.settings.registry import REGISTRY

    d = REGISTRY[KEY]
    assert d.default is True
    assert d.type.value.lower() == "bool"


async def test_every_shop_keeps_working_as_before_a_manager_still_sees_the_reports(
    db, tenant_ctx
) -> None:
    got = await _all(db, tenant_ctx, "manager")
    assert all(code not in (401, 403) for code in got.values()), got


async def test_the_owner_turns_it_off_and_a_manager_is_refused_on_every_route(
    db, tenant_ctx
) -> None:
    await SettingsService(db, tenant_ctx.tenant_id).set(KEY, False)
    got = await _all(db, tenant_ctx, "manager")
    assert set(got.values()) == {403}, got


async def test_the_owner_always_gets_in_even_with_it_off(db, tenant_ctx) -> None:
    await SettingsService(db, tenant_ctx.tenant_id).set(KEY, False)
    got = await _all(db, tenant_ctx, "owner")
    assert all(code not in (401, 403) for code in got.values()), got


@pytest.mark.parametrize("setting", [True, False])
async def test_a_cashier_is_refused_whatever_the_shop_set(db, tenant_ctx, setting) -> None:
    await SettingsService(db, tenant_ctx.tenant_id).set(KEY, setting)
    got = await _all(db, tenant_ctx, "staff")
    assert set(got.values()) == {403}, got


async def test_turning_it_back_on_gives_the_manager_the_reports_again(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(KEY, False)
    assert set((await _all(db, tenant_ctx, "manager")).values()) == {403}
    await svc.set(KEY, True)
    got = await _all(db, tenant_ctx, "manager")
    assert all(code not in (401, 403) for code in got.values()), got


async def test_a_shop_that_never_set_it_reads_on(db, tenant_ctx) -> None:
    assert (await SettingsService(db, tenant_ctx.tenant_id).resolve(KEY)).value is True


async def test_another_shops_choice_does_not_reach_this_one(db, tenant_ctx) -> None:
    import uuid

    other = uuid.uuid4()
    resolved = await SettingsService(db, other).resolve(KEY)
    assert resolved.value is True
    await SettingsService(db, tenant_ctx.tenant_id).set(KEY, False)
    assert (await SettingsService(db, other).resolve(KEY)).value is True


async def test_the_owner_is_known_by_what_the_role_can_do_not_by_its_name(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import _call

    await SettingsService(db, tenant_ctx.tenant_id).set(KEY, False)
    granted = ROLES["manager"] | {"settings:write"}
    for path in GETS:
        r = await _call(db, tenant_ctx, "GET", path, perms=granted)
        assert r.status_code not in (401, 403), path


@pytest.mark.parametrize("stored", ["false", "no", 0, 1, "true", [], None])
async def test_only_a_real_true_opens_the_reports_to_a_manager(db, tenant_ctx, stored) -> None:
    """A value that is not the boolean true (a stray string or number written by a script) never
    opens the money reports: the shop's money is shown only on an explicit yes."""
    from sqlalchemy import text

    await db.execute(
        text(
            "INSERT INTO tenant_settings (id, tenant_id, key, scope, scope_id, value) "
            "VALUES (gen_random_uuid(), :t, :k, 'tenant', NULL, CAST(:v AS jsonb))"
        ),
        {"t": tenant_ctx.tenant_id, "k": KEY, "v": __import__("json").dumps({"v": stored})},
    )
    got = await _all(db, tenant_ctx, "manager")
    assert set(got.values()) == {403}, (stored, got)
