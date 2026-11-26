"""Two production deaths, pinned so they cannot come back.

1. ``platform_monitors`` called ``monitors.notify_operators(...)`` — a function
   that moved out of the monitors module in 338b5dbc ("the monitors glue
   belongs to the workers layer") and never existed again. Every run died with
   AttributeError, so no operator email and no tenant alert was ever sent.
   The pin walks the module for ``monitors.<attr>`` references and fails on any
   that is not actually defined there.

2. ``audit_retention_sweep`` deleted audit rows under a policy that
   ``fe2026112503`` created, while the ``GRANT DELETE`` it delegated to "the
   provision script" never reached production (``fd2026100409`` had revoked
   it). Every run raised ``InsufficientPrivilegeError: permission denied for
   table audit_logs``. The pin requires a migration that grants DELETE on
   audit_logs to sales_app, so the privilege cannot live only in a script that
   production never runs.
"""

from __future__ import annotations

import ast
import pathlib

from app.modules.platform.services import monitors

_WORKER = pathlib.Path(__file__).resolve().parents[1] / "app/workers/scheduler_worker.py"
_VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations/versions"


def test_every_monitors_attribute_the_worker_uses_exists() -> None:
    tree = ast.parse(_WORKER.read_text(encoding="utf-8"))
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "monitors"
    }
    assert used, "the worker no longer touches the monitors module at all?"
    missing = sorted(name for name in used if not hasattr(monitors, name))
    assert not missing, (
        f"the worker calls monitors.{{{', '.join(missing)}}} which the module does "
        "not define — every platform_monitors run will die with AttributeError"
    )


def test_a_migration_grants_delete_on_audit_logs() -> None:
    granting = [
        path.name
        for path in _VERSIONS.glob("*.py")
        if "GRANT DELETE ON public.audit_logs TO sales_app" in path.read_text(encoding="utf-8")
    ]
    assert granting, (
        "no migration grants DELETE on audit_logs to sales_app: the retention "
        "sweep's policy exists but the privilege does, so every audit_retention_sweep "
        "fails with 'permission denied for table audit_logs'"
    )
