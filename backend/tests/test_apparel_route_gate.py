"""The gate is attached to the trading routers, and its mode is honest.

Three things can go wrong and each is checked here: a router left ungated, a
mode that blocks when it promised not to, and an enforce mode that swallows the
denial. The last one is the dangerous one: a gate that logs instead of refusing
reads as enforcement in the code and is not.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.applications.apparel import guard as guard_module
from app.applications.apparel.guard import require_apparel
from app.applications.apparel.permissions import PERMISSIONS
from app.applications.apparel.route_gate import ROUTER_PERMISSIONS, gate_routers
from app.core.errors import PermissionDeniedError


class FakeRouter:
    def __init__(self) -> None:
        self.dependencies: list[object] = []


def _ctx(held: frozenset[str] = frozenset()) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id="t",
        workspace_id="w",
        user=SimpleNamespace(id="u"),
        permission_codes=held,
        session=None,
    )


def _mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(
        guard_module, "get_settings", lambda: SimpleNamespace(apparel_gate_mode=mode)
    )


def test_every_router_is_gated_once() -> None:
    routers = {key: FakeRouter() for key in ROUTER_PERMISSIONS}
    attached = gate_routers(*[(router, key) for key, router in routers.items()])
    assert attached == len(ROUTER_PERMISSIONS)
    for key, router in routers.items():
        assert len(router.dependencies) == 1, f"{key} router is not gated"


def test_attaching_twice_does_not_stack_gates() -> None:
    router = FakeRouter()
    gate_routers((router, "catalog"))
    assert gate_routers((router, "catalog")) == 0
    assert len(router.dependencies) == 1


def test_an_undeclared_module_fails_loudly() -> None:
    with pytest.raises(KeyError):
        gate_routers((FakeRouter(), "pharmacy"))


def test_every_router_permission_exists() -> None:
    known = {permission.code for permission in PERMISSIONS}
    unknown = {code for code in ROUTER_PERMISSIONS.values() if code not in known}
    assert unknown == set()


def test_shadow_mode_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    _mode(monkeypatch, "shadow")
    dependency = require_apparel("apparel.pos.access")
    assert asyncio.run(dependency(ctx=_ctx())) is None


def test_enforce_mode_refuses_a_user_without_the_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mode(monkeypatch, "enforce")
    dependency = require_apparel("apparel.pos.access")
    with pytest.raises(PermissionDeniedError):
        asyncio.run(dependency(ctx=_ctx()))


def test_enforce_mode_allows_a_user_holding_the_legacy_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mode(monkeypatch, "enforce")
    dependency = require_apparel("apparel.pos.access")
    access = asyncio.run(dependency(ctx=_ctx(frozenset({"orders:read"}))))
    assert access is not None
    assert access.permission_code == "apparel.pos.access"


def test_off_mode_does_not_consult_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _mode(monkeypatch, "off")
    dependency = require_apparel("apparel.pos.access")
    assert asyncio.run(dependency(ctx=_ctx())) is None
