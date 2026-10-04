"""§189 POS adapter — contract guards (P6/P7).

DB-free pins: the POS routes are mounted, and the cash-movement wire contract
itself refuses the sell-flow-only reasons — a hand-written cash_sale would
book money no order claims, so the refusal must live on the wire too.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.main import create_app

SELL_PATH = "/api/v1/pos/sessions/{session_id}/sell"
CLOSE_PATH = "/api/v1/pos/sessions/{session_id}/close"
CASH_PATH = "/api/v1/pos/sessions/{session_id}/cash-movements"
OPEN_PATH = "/api/v1/pos/registers/{register_id}/sessions"
REGISTERS_PATH = "/api/v1/pos/registers"


def test_pos_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {REGISTERS_PATH, OPEN_PATH, SELL_PATH, CLOSE_PATH, CASH_PATH} <= paths


def test_wire_refuses_sale_only_cash_reasons() -> None:
    from app.modules.pos.router import CashMovementRequest

    with pytest.raises(PydanticValidationError):
        CashMovementRequest(direction="in", reason="cash_sale", amount="5.00")
    row = CashMovementRequest(direction="in", reason="float_adjust", amount="5.00")
    assert row.reason == "float_adjust"
