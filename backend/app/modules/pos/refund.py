"""Refund settlement: which tender the money goes back on, and how much of it.

Pure functions only — no database, no clock, no session. The cashier service loads the original
sale's captured payments and the refunds already made against them, hands them in here, and
writes whatever this module returns. Keeping the arithmetic here means it is tested without a
database and cannot drift between a return, an exchange and a void.

## The policy, in the shop's own words

A customer comes back with a shirt and wants their money. The money came in on one or more
tenders (200 cash + 300 card, say). The refund has to go back the way it came in, because that is
the only version the books and the bank statement can both prove.

1. **Cash first.** A customer standing at the counter wants the notes back before a card reversal
   they have to wait three days for. Cash also has a drawer movement we can show them.
2. **Then the remaining tenders in the order they were taken.** Deterministic, and it matches the
   receipt the customer is holding.
3. **A tender never gives back more than it collected, minus what it already gave back.** That is
   the whole cap: no configuration can refund a card that was never charged.
4. **Whatever the sale never collected is not refunded.** A sale on account, or one covered by a
   customer deposit, has value that never entered a tender. That part comes back as a recorded
   `uncollected` amount — it reduces what the customer owes, it does not come out of the drawer.

The result is a list of slices, one per tender, each naming the payment row it reverses. Every
slice becomes a `Refund` row against that payment, so "where did this money go" is answerable from
the database alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.errors import ValidationError
from app.modules.pos.tender import CASH, to_money

ZERO = Decimal("0.00")

# Payment states that mean money ACTUALLY ARRIVED, so the tender can give some back. The first
# partial refund flips a payment to `partially_refunded`; leaving that state out of the lookup made
# the second return on one invoice unable to find the tender it must refund from.
REFUNDABLE_PAYMENT_STATES = ("captured", "partially_refunded", "refunded")

# Refund rows that already count against a tender's room. `pending` is included on purpose: a
# card/wallet reversal the cashier has not yet confirmed with its terminal reference is money
# promised to the customer, and paying it again before it is confirmed would be a double refund.
REFUND_COUNTED_STATES = ("pending", "approved", "processed")


@dataclass(frozen=True, slots=True)
class Tender:
    """One way the original sale was actually paid, and how much of it already went back."""

    payment_id: uuid.UUID | None
    method: str
    amount: Decimal
    refunded: Decimal = ZERO

    @property
    def room(self) -> Decimal:
        """What this tender can still give back."""
        return to_money(self.amount - self.refunded, "room")


@dataclass(frozen=True, slots=True)
class RefundSlice:
    """One tender's share of one refund: the row that proves where the money went."""

    payment_id: uuid.UUID | None
    method: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class RefundPlan:
    """The whole answer: what to refund, on which tenders, and what never came in."""

    slices: tuple[RefundSlice, ...]
    refunded: Decimal
    uncollected: Decimal

    @property
    def by_method(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for slice_ in self.slices:
            totals[slice_.method] = totals.get(slice_.method, ZERO) + slice_.amount
        return {method: to_money(amount, method) for method, amount in totals.items()}

    @property
    def cash(self) -> Decimal:
        """The part that comes out of the drawer as cash."""
        return to_money(self.by_method.get(CASH, ZERO), "cash")


def _ordered(tenders: Iterable[Tender]) -> list[Tender]:
    """Cash first, then the rest in the order they were taken.

    ``sorted`` is stable, so the non-cash tenders keep their original order.
    """
    return sorted(tenders, key=lambda t: 0 if t.method == CASH else 1)


def allocate(amount: object, tenders: Sequence[Tender]) -> RefundPlan:
    """Split one refund across the tenders that can still give it back.

    Returns the slices plus whatever could not be covered. A non-zero ``uncollected`` is not an
    error: it is value the sale never collected (on account, or paid by a deposit), which the
    caller records against what the customer owes instead of paying out of the drawer.
    """
    remaining = to_money(amount, "refund amount")
    if remaining < ZERO:
        raise ValidationError("a refund cannot be negative")
    slices: list[RefundSlice] = []
    for tender in _ordered(tenders):
        if remaining <= ZERO:
            break
        room = tender.room
        if room <= ZERO:
            continue
        take = to_money(min(room, remaining), "slice")
        if take <= ZERO:
            continue
        slices.append(RefundSlice(tender.payment_id, tender.method, take))
        remaining -= take
    refunded = to_money(sum((s.amount for s in slices), ZERO), "refunded")
    return RefundPlan(tuple(slices), refunded, to_money(remaining, "uncollected"))


def allocate_by_method(
    requested: Sequence[tuple[str, object]], tenders: Sequence[Tender]
) -> RefundPlan:
    """Split a refund the way the cashier asked for it: ``(method, amount)`` pairs.

    Used when the shop's policy allows the cashier to choose (give the notes back even though the
    customer paid by card, when the card terminal is down). Every pair must be satisfiable from
    that method's remaining room, so the refund still points at a real payment. Asking for more
    than a method collected is refused rather than silently re-routed.
    """
    rooms: dict[str, Decimal] = {}
    by_method: dict[str, list[Tender]] = {}
    for tender in tenders:
        rooms[tender.method] = rooms.get(tender.method, ZERO) + tender.room
        by_method.setdefault(tender.method, []).append(tender)

    slices: list[RefundSlice] = []
    for method, raw in requested:
        method = str(method).strip()
        if method not in by_method:
            raise ValidationError(
                f"cannot refund {method!r}: the sale never collected it "
                f"(collected {sorted(by_method)})"
            )
        amount = to_money(raw, f"refund {method}")
        if amount <= ZERO:
            raise ValidationError(f"refund amount for {method!r} must be greater than zero")
        room = to_money(rooms.get(method, ZERO), method)
        if amount > room:
            raise ValidationError(
                f"refund {amount} on {method!r} exceeds the {room} that method still holds"
            )
        # Spread this method's own amount over its payments, oldest first.
        remaining = amount
        for tender in by_method[method]:
            if remaining <= ZERO:
                break
            take = to_money(min(tender.room, remaining), "slice")
            if take <= ZERO:
                continue
            slices.append(RefundSlice(tender.payment_id, method, take))
            remaining -= take
        rooms[method] = to_money(room - amount, method)

    refunded = to_money(sum((s.amount for s in slices), ZERO), "refunded")
    total_room = to_money(sum((t.room for t in tenders), ZERO), "room")
    uncollected = to_money(total_room - refunded, "uncollected")
    return RefundPlan(tuple(slices), refunded, max(uncollected, ZERO))


def plan_for(
    amount: object,
    tenders: Sequence[Tender],
    *,
    requested: Sequence[tuple[str, object]] | None = None,
) -> RefundPlan:
    """The one entry point the services call: requested methods when given, else the policy."""
    if requested:
        return allocate_by_method(requested, tenders)
    return allocate(amount, tenders)
