"""A cart line has a shape: a real variant id and a whole-number quantity of at least one.

``items`` used to be ``list[dict]`` with no schema, so ``quantity: true`` became 1, ``"2"`` or
``2.5`` slipped through and a missing variant surfaced as a server error. The request schema now
refuses them with a 422 before anything is priced. Extra keys (a title, a display price) are
dropped, not trusted, so an existing screen keeps working.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.pos.router import HoldCartRequest, QuoteRequest, RecordSaleRequest

VID = "5b6f0b9e-1c1d-4f5e-9a47-0a8f6d2c1e11"


@pytest.mark.parametrize("model", [RecordSaleRequest, QuoteRequest, HoldCartRequest])
@pytest.mark.parametrize(
    "bad",
    [
        {"variant_id": VID, "quantity": True},
        {"variant_id": VID, "quantity": 2.5},
        {"variant_id": VID, "quantity": "2"},
        {"variant_id": VID, "quantity": 0},
        {"variant_id": VID, "quantity": -1},
        {"variant_id": VID},
        {"quantity": 1},
        {"variant_id": "not-a-uuid", "quantity": 1},
        {"variant_id": VID, "quantity": 1, "discount_pct": "101"},
        {"variant_id": VID, "quantity": 1, "discount_pct": "-5"},
        {"variant_id": VID, "quantity": 1, "discount_pct": "abc"},
    ],
)
def test_a_malformed_line_is_refused(model, bad) -> None:
    with pytest.raises(ValidationError):
        model(items=[bad])


@pytest.mark.parametrize("model", [RecordSaleRequest, QuoteRequest, HoldCartRequest])
def test_a_good_line_passes_and_extra_keys_are_dropped(model) -> None:
    req = model(items=[{"variant_id": VID, "quantity": 3, "discount_pct": "10", "title": "تيشيرت"}])
    line = req.items[0]
    assert str(line.variant_id) == VID and line.quantity == 3
    assert "title" not in line.model_dump()


from app.modules.pos.router import ExchangeRequest, ReturnRequest  # noqa: E402

OID = "7c1f0b9e-1c1d-4f5e-9a47-0a8f6d2c1e22"


@pytest.mark.parametrize("qty", [True, False, 2.5, "2", 0, -1, None])
def test_a_return_line_refuses_a_loose_quantity(qty) -> None:
    with pytest.raises(ValidationError):
        ReturnRequest(order_id=OID, lines=[{"variant_id": VID, "quantity": qty}])


@pytest.mark.parametrize("qty", [True, False, 2.5, "2", 0, -1, None])
def test_an_exchange_line_refuses_a_loose_quantity(qty) -> None:
    good = [{"variant_id": VID, "quantity": 1}]
    with pytest.raises(ValidationError):
        ExchangeRequest(
            order_id=OID, return_lines=[{"variant_id": VID, "quantity": qty}], new_lines=good
        )
    with pytest.raises(ValidationError):
        ExchangeRequest(
            order_id=OID, return_lines=good, new_lines=[{"variant_id": VID, "quantity": qty}]
        )


def test_a_whole_quantity_still_passes_on_returns_and_exchanges() -> None:
    line = [{"variant_id": VID, "quantity": 2}]
    assert ReturnRequest(order_id=OID, lines=line).lines[0].quantity == 2
    assert (
        ExchangeRequest(order_id=OID, return_lines=line, new_lines=line).new_lines[0].quantity == 2
    )
