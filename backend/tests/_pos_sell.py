"""The recording stand-in for the removed paid ``PosService.sell`` (no test-module imports, so
any test file can import it without a cycle)."""

from __future__ import annotations

from app.modules.pos.service import PosService


async def sell(
    db,
    tenant_id,
    session_id,
    *,
    items,
    customer_id=None,
    discount_total=None,
    note=None,
    actor_user_id=None,
    **_ignored_payment_fields,
):
    """Record a sale on the till that owns ``session_id`` (the cashier records, never takes money).

    Stands in for the removed paid ``PosService.sell``: the shift is resolved to its register and
    the sale is recorded through ``record_sale``. Payment fields (tenders, method, amount,
    tendered_cash) are accepted and ignored, because nothing is paid in this layer anymore.
    """
    pos_session = await PosService._get_session(db, tenant_id, session_id)
    return await PosService.record_sale(
        db,
        tenant_id,
        pos_session.register_id,
        items=items,
        customer_id=customer_id,
        discount_total=discount_total,
        note=note,
        actor_user_id=actor_user_id,
    )
