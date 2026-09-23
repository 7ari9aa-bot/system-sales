"""M9 — the stock ledger's reason vocabulary is a closed set, not free text.

`inventory_movements.reason` was a free-text column written through a free-text
request field, so "what happened to this stock" was unanswerable: every writer
invented its own word and no filter, report or reconciliation could group by it.
This pins the vocabulary the system ACTUALLY uses, enumerated from the writers
that exist today:

    purchase           seed_demo / restock intake            (`in`)
    sale               reservation converted on capture      (service.convert)
    return             goods back on the order_return saga    (orders/returns)
    return_reversal    the saga's compensation                (orders/returns)
    transfer_in/out    complete_transfer                      (service)
    adjustment         the manual stocktake route             (router default)
    damage             documented shrinkage reason            (models docstring)
    reservation        a hold — availability, not on_hand     (NEW, service.reserve)
    reservation_release a hold given back                     (NEW, service.release)

The last two are AVAILABILITY reasons: they pair with the `hold`/`release`
directions and never change `on_hand`. They are machine-written by the
reservation machinery, so the human write surface (POST /inventory/movements)
must refuse them — a hand-typed "reservation" row would break the
hold/release pairing the ledger is being extended to support.

Validation has to happen BEFORE the session is touched, so the pure cases below
run with `session=None` — the same idiom
`test_billing_metering.test_a_bad_period_is_rejected_before_the_session_is_touched`
uses. A bad reason must be a domain 400 (`ValidationError`), never an
AttributeError on a None session and never a 500.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.modules.inventory import service as inventory_service
from app.modules.inventory.router import MovementRequest
from app.modules.inventory.service import InventoryService

# Reasons every writer in the codebase passes today, plus the two hold reasons.
PHYSICAL_REASONS = {
    "purchase",
    "sale",
    "return",
    "return_reversal",
    "transfer_in",
    "transfer_out",
    "adjustment",
    "damage",
}
AVAILABILITY_REASONS = {"reservation", "reservation_release"}


def _move(**kw):
    """Call the service with a dead session: only up-front validation can pass."""
    return InventoryService.move(
        None,  # type: ignore[arg-type] — validation must run before it is used
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        **kw,
    )


# ------------------------------------------------------- the vocabulary -----


def test_the_ledger_exports_its_reason_vocabulary() -> None:
    """The set lives in the domain service, so every writer shares one list."""
    assert set(inventory_service.MOVEMENT_REASONS) == PHYSICAL_REASONS | AVAILABILITY_REASONS
    assert set(inventory_service.PHYSICAL_MOVEMENT_REASONS) == PHYSICAL_REASONS
    assert set(inventory_service.AVAILABILITY_MOVEMENT_REASONS) == AVAILABILITY_REASONS


async def test_an_unknown_reason_is_refused_before_the_session_is_touched() -> None:
    """The bug: `reason` was free text, so this used to be a valid request.

    `session=None` is the assertion — reaching the database would raise
    AttributeError, so a clean ValidationError proves the guard runs first.
    """
    with pytest.raises(inventory_service.ValidationError, match="reason"):
        await _move(direction="in", quantity=1, reason="because-i-said-so")


async def test_a_blank_or_oversized_reason_is_refused() -> None:
    for junk in ("", "   ", "x" * 64):
        with pytest.raises(inventory_service.ValidationError):
            await _move(direction="in", quantity=1, reason=junk)


@pytest.mark.parametrize("reason", sorted(PHYSICAL_REASONS))
async def test_every_existing_writer_still_works(reason: str) -> None:
    """Narrowing must not break a legitimate caller: each reason the code
    already writes has to survive the constraint."""
    with pytest.raises(AttributeError):  # validation passed; the None session fails
        await _move(direction="in", quantity=1, reason=reason)


# --------------------------------------------------- direction/reason pair --


async def test_a_hold_reason_cannot_masquerade_as_physical_stock() -> None:
    """`in`/`out`/`adjust` change on_hand; an availability reason must not be
    written against them, or a hold would read as goods leaving the warehouse."""
    with pytest.raises(inventory_service.ValidationError, match="direction"):
        await _move(direction="out", quantity=1, reason="reservation")


async def test_a_physical_reason_cannot_be_written_as_an_availability_row() -> None:
    with pytest.raises(inventory_service.ValidationError, match="direction"):
        await _move(direction="hold", quantity=1, reason="purchase")


async def test_an_unknown_direction_is_still_a_valueerror() -> None:
    """Unchanged behaviour: `test_move_rejects_bad_input` pins ValueError here."""
    with pytest.raises(ValueError):
        await _move(direction="sideways", quantity=1, reason="purchase")


async def test_a_well_formed_hold_cannot_be_written_through_move() -> None:
    """`hold`+`reservation` passes the shape check, and `move` must still refuse
    it: a row appended without `reserve()` moving `reserved` would be a hold the
    balance does not know about. Only reserve()/release() write availability."""
    with pytest.raises(inventory_service.ValidationError, match="reserve"):
        await _move(direction="hold", quantity=1, reason="reservation")


async def test_the_internal_appender_validates_too() -> None:
    """`_append` is the single writer of the ledger, so the shape check lives
    there — a future service method that forgets its own guard still cannot
    append a row the ledger cannot be read back by. The `out`/`sale` row of
    `convert()` is written this way."""
    with pytest.raises(inventory_service.ValidationError):
        await InventoryService._append(
            None,  # type: ignore[arg-type] — validation must precede any query
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            direction="out",
            quantity=1,
            reason="goods-left-for-unknown-reasons",
            balance_after=0,
        )


# ------------------------------------------------- the human write surface --


def _request(**kw) -> MovementRequest:
    base = {
        "variant_id": uuid.uuid4(),
        "warehouse_id": uuid.uuid4(),
        "direction": "in",
        "quantity": 1,
    }
    return MovementRequest(**{**base, **kw})


@pytest.mark.parametrize("reason", sorted(PHYSICAL_REASONS))
def test_the_manual_surface_accepts_each_physical_reason(reason: str) -> None:
    assert _request(reason=reason).reason == reason


def test_the_manual_surface_defaults_to_adjustment() -> None:
    assert _request().reason == "adjustment"


@pytest.mark.parametrize(
    "reason",
    ["because-i-said-so", "", "PURCHASE", "damage "] + sorted(AVAILABILITY_REASONS),
)
def test_the_manual_surface_refuses_junk_and_forged_holds(reason: str) -> None:
    """The two hold reasons are machine-written; typing one by hand would
    fabricate a reservation row the release pairing can never find."""
    with pytest.raises(PydanticValidationError):
        _request(reason=reason)


@pytest.mark.parametrize("direction", ["hold", "release", "HOLD", "sideways"])
def test_the_manual_surface_cannot_write_availability_rows(direction: str) -> None:
    with pytest.raises(PydanticValidationError):
        _request(direction=direction, reason="adjustment")
