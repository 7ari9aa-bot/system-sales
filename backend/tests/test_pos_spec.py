"""§189 POS adapter — contract guards.

DB-free pins: the POS routes are mounted, and the manual cash-movement and
drawer-handover routes stay gone (the cashier records sales, it does not move money).
"""

from __future__ import annotations

from app.main import create_app

SELL_PATH = "/api/v1/pos/sessions/{session_id}/sell"
CLOSE_PATH = "/api/v1/pos/sessions/{session_id}/close"
OPEN_PATH = "/api/v1/pos/registers/{register_id}/sessions"
REGISTERS_PATH = "/api/v1/pos/registers"


def test_pos_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {REGISTERS_PATH, OPEN_PATH, SELL_PATH, CLOSE_PATH} <= paths


def test_manual_cash_and_handover_routes_stay_removed() -> None:
    paths = set(create_app().openapi()["paths"])
    pos = {p for p in paths if p.startswith("/api/v1/pos/")}
    assert not [p for p in pos if "cash-movements" in p or "handover" in p]
