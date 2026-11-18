"""§189 POS adapter — contract guards.

DB-free pins: the POS routes are mounted, and the routes that move money or open a day without a
real balance stay gone (the cashier records sales, it does not move money).
"""

from __future__ import annotations

from app.main import create_app

SELL_PATH = "/api/v1/pos/sessions/{session_id}/sell"
REFUNDS_PATH = "/api/v1/pos/sessions/{session_id}/refunds"
CLOSE_PATH = "/api/v1/pos/sessions/{session_id}/close"
OPEN_PATH = "/api/v1/pos/registers/{register_id}/sessions"
OPEN_DAY_PATH = "/api/v1/pos/registers/{register_id}/open-day"
RECORD_SALE_PATH = "/api/v1/pos/registers/{register_id}/sales"
REGISTERS_PATH = "/api/v1/pos/registers"


def test_pos_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {REGISTERS_PATH, OPEN_DAY_PATH, RECORD_SALE_PATH, CLOSE_PATH} <= paths


def test_the_paid_and_default_balance_routes_stay_removed() -> None:
    """/sell and /refunds take and return money; the old open takes a default 0.00 balance."""
    paths = set(create_app().openapi()["paths"])
    assert not {SELL_PATH, REFUNDS_PATH, OPEN_PATH} & paths


def test_manual_cash_and_handover_routes_are_permission_guarded() -> None:
    """Petty cash (pay-in / pay-out / drop) and the drawer handover were added on purpose with the
    supply-chain wave (migration fe2026111728). They move money between people, so what must hold is
    that every one of them sits behind a real RBAC permission, not that they are absent."""
    from app.modules.identity.deps import require_permission

    def permissions(dependant) -> set[str]:  # noqa: ANN001
        found: set[str] = set()
        for sub in dependant.dependencies:
            if isinstance(sub.call, require_permission):
                found.add(sub.call.code)
            found |= permissions(sub)
        return found

    # FastAPI keeps included routers lazy; the tenant matrix already knows how to flatten them.
    from tests.security.test_tenant_access_matrix import _walk_routes

    required: dict[tuple[str, str], set[str]] = {}
    for route in _walk_routes(create_app()):
        path = (
            route.path
        )  # routers are mounted under /api/v1, so the route's own path has no prefix
        if path.startswith("/pos/") and ("cash-movements" in path or "handover" in path):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                required[(method, path)] = permissions(route.dependant)

    assert required, "the petty-cash and handover routes are expected to exist"
    # Reading movements needs the read permission; moving money or the drawer needs write.
    for (method, path), codes in required.items():
        want = "orders:read" if method == "GET" else "orders:write"
        assert want in codes, f"{method} {path} is not behind {want}: {sorted(codes)}"
