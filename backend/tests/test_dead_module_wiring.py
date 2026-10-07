"""Pinned callers for modules this task wired out of the dead set.

``tests/test_no_dead_modules.py`` proves these modules are *reachable*
transitively, but reachability alone does not pin WHICH caller is load-bearing.
DB-backed endpoint tests skip locally (no ``DATABASE_URL_APP_ADMIN``), so a
"the route returns a dr row" assertion would be a green-in-CI-only claim. These
tests therefore pin the caller in a way that RUNS locally:

* ``app.modules.platform.router`` is the sole runtime caller of
  ``app.modules.platform.dr`` (the §103 health indicator). We assert the import
  edge statically AND drive ``_dr_subsystem`` directly over a fake session with
  a stubbed ``DRService``, so the status mapping is proven without a database.
* ``app.modules.conversations.gateway.registry`` is the sole caller of
  ``app.modules.conversations.gateway.email``. We assert ``get_adapter("email")``
  actually returns the registered ``EmailAdapter`` and that it parses an
  inbound payload — the whole point of the adapter — with no network.

Both are same-module edges, so neither moves the boundary ratchet.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
PLATFORM_ROUTER = BACKEND_ROOT / "app" / "modules" / "platform" / "router.py"
GATEWAY_REGISTRY = BACKEND_ROOT / "app" / "modules" / "conversations" / "gateway" / "registry.py"


def _imported_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# ---------------------------------------------------------------- dr.py -----


def test_platform_router_imports_the_dr_service() -> None:
    """The §103 health route is what binds DRService into the app."""
    imported = _imported_names(PLATFORM_ROUTER)
    assert "app.modules.platform.dr" in imported, (
        "platform.router must import app.modules.platform.dr — it is dr.py's "
        "only caller; the health indicator is its whole reason to exist"
    )
    assert "app.modules.platform.dr.DRService" in imported


async def test_dr_subsystem_maps_health_states(monkeypatch: pytest.MonkeyPatch) -> None:
    """_dr_subsystem turns a DRService.check_dr_health result into a row."""
    from app.modules.platform import router as platform_router

    class _FakeService:
        def __init__(self, result: dict | None, raises: bool = False) -> None:
            self._result = result
            self._raises = raises

        async def check_dr_health(self, session: object) -> dict:
            if self._raises:
                raise RuntimeError("db down")
            assert self._result is not None
            return self._result

    class _FakeCtx:
        session = object()

    cases = [
        ({"healthy": True, "restore_test_overdue": False}, "healthy"),
        ({"healthy": False, "restore_test_overdue": True}, "degraded"),
        ({"healthy": False, "restore_test_overdue": False}, "degraded"),
    ]
    for result, expected in cases:
        monkeypatch.setattr(platform_router, "DRService", _FakeService(result))
        row = await platform_router._dr_subsystem(_FakeCtx())
        assert row["name"] == "dr"
        assert row["status"] == expected

    monkeypatch.setattr(platform_router, "DRService", _FakeService(None, raises=True))
    raised = await platform_router._dr_subsystem(_FakeCtx())
    assert raised["status"] == "degraded", "a failing DR check must degrade, never raise"


# ------------------------------------------------------------- email.py -----


def test_gateway_registry_imports_and_registers_email() -> None:
    """The adapter registry is what makes the email channel resolvable."""
    imported = _imported_names(GATEWAY_REGISTRY)
    assert "app.modules.conversations.gateway.email" in imported, (
        "gateway.registry must import the email adapter — it is email.py's "
        "only caller; an unregistered channel is a silent inbound drop"
    )
    assert "app.modules.conversations.gateway.email.email_adapter" in imported


def test_get_adapter_resolves_email_channel() -> None:
    from app.modules.conversations.gateway.email import EmailAdapter
    from app.modules.conversations.gateway.registry import get_adapter

    adapter = get_adapter("email")
    assert isinstance(adapter, EmailAdapter)
    assert adapter.name == "email"
    assert adapter.channel == "email"


async def test_email_adapter_parses_inbound_sendgrid_webhook() -> None:
    """The registered adapter normalizes a real SendGrid payload end to end."""
    from app.modules.conversations.gateway.registry import get_adapter

    adapter = get_adapter("email")
    assert adapter is not None
    # 5.1 reshaped every adapter to the SAME contract: sync, one payload
    # argument, and a LIST of canonical messages the dispatcher iterates.
    inbound = adapter.parse_inbound(
        {"from": "Dana <dana@example.com>", "to": "sales@tenant.test", "text": "hello"}
    )
    assert len(inbound) == 1
    message = inbound[0]
    assert message.channel == "email"
    assert message.customer_ref == "Dana <dana@example.com>"
    assert message.customer_name == "Dana"
    assert message.body == "hello"
    assert message.conversation_ref == "sales@tenant.test"
