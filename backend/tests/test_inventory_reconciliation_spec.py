"""§188 inventory reconciliation — contract guards (P4).

DB-free pins: the findings routes are mounted, the sweep is declared in
RECURRING_JOBS (so a tenant's row actually gets seeded — the §82 lesson),
and its handler is registered.
"""

from __future__ import annotations

from app.main import create_app

FINDINGS_PATH = "/api/v1/inventory/reconciliation/findings"
RESOLVE_PATH = "/api/v1/inventory/reconciliation/findings/{finding_id}/resolve"


def test_reconciliation_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert FINDINGS_PATH in paths
    assert RESOLVE_PATH in paths


def test_reconciliation_sweep_is_declared_and_registered() -> None:
    from app.workers.scheduler_worker import _HANDLERS, RECURRING_JOBS

    assert "reconcile_inventory" in RECURRING_JOBS
    assert "reconcile_inventory" in _HANDLERS
