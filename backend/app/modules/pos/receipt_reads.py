"""POS receipt reads: fetching, listing and searching issued receipts.

Split out of ``service.py`` so that file stays navigable. These methods only read: they
call no other ``PosService`` method and do no date arithmetic, so moving them cannot change
behaviour or the clock that tests freeze on ``app.modules.pos.service.datetime``.
``PosService`` inherits this class, so every caller still writes ``PosService.get_receipt(...)``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError, ValidationError
from app.modules.orders.money import to_money
from app.modules.pos.models import PosReceipt, PosReturnLine


class PosReceiptReads:
    """Read-only receipt queries; static methods taking (session, tenant_id)."""

    @staticmethod
    async def get_receipt(session: AsyncSession, tenant_id: UUID, receipt_id: UUID) -> dict:
        """The printed artifact: receipt header + order lines (+ payments an OLD sale recorded).

        Read-only and assembled from the owning modules' tables through this
        one parameter-bound read model (§137) — the till never writes them.
        """
        from app.modules.orders.models import Order, OrderItem, OrderPayment

        receipt = (
            await session.execute(
                select(PosReceipt).where(
                    PosReceipt.tenant_id == tenant_id, PosReceipt.id == receipt_id
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError(f"pos receipt {receipt_id} not found")
        order = (
            await session.execute(
                select(Order).where(Order.tenant_id == tenant_id, Order.id == receipt.order_id)
            )
        ).scalar_one_or_none()
        lines = (
            (
                await session.execute(
                    select(OrderItem).where(
                        OrderItem.tenant_id == tenant_id,
                        OrderItem.order_id == receipt.order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        tenders = (
            (
                await session.execute(
                    select(OrderPayment).where(
                        OrderPayment.tenant_id == tenant_id,
                        OrderPayment.order_id == receipt.order_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Return state of the ORDER, derived from the return lines — the
        # derived equivalent of ERPNext's "Credit Note Issued" marker.
        returned_by_variant: dict[UUID, int] = dict(
            (
                await session.execute(
                    select(
                        PosReturnLine.variant_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id == receipt.order_id,
                    )
                    .group_by(PosReturnLine.variant_id)
                )
            ).all()
        )
        if receipt.kind == "return":
            # A return receipt shows what THIS return gave back, priced at the
            # original sale's lines.
            return_rows = (
                (
                    await session.execute(
                        select(PosReturnLine).where(
                            PosReturnLine.tenant_id == tenant_id,
                            PosReturnLine.receipt_id == receipt.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            item_by_variant = {item.variant_id: item for item in lines}
            lines_payload = [
                {
                    "variant_id": row.variant_id,
                    "title": (
                        item_by_variant[row.variant_id].title
                        if row.variant_id in item_by_variant
                        else None
                    ),
                    "sku": (
                        item_by_variant[row.variant_id].sku
                        if row.variant_id in item_by_variant
                        else None
                    ),
                    "quantity": row.quantity,
                    "unit_price": str(row.unit_price),
                    "total": str(row.refund_total),
                    "returned_qty": row.quantity,
                }
                for row in return_rows
            ]
        else:
            lines_payload = [
                {
                    "variant_id": line.variant_id,
                    "title": line.title,
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": str(line.unit_price),
                    # The line's own discount: a client prices a return the way the server does
                    # (the customer paid gross minus THIS, not a share of the basket discount).
                    "discount_pct": str(
                        Decimal(str(line.discount_pct or 0)).quantize(Decimal("0.01"))
                    ),
                    "total": str(line.total),
                    "returned_qty": int(returned_by_variant.get(line.variant_id, 0)),
                }
                for line in lines
            ]
        fully_returned = bool(lines) and all(
            int(returned_by_variant.get(item.variant_id, 0)) >= item.quantity for item in lines
        )
        return {
            "receipt": {
                "id": receipt.id,
                "number": receipt.number,
                "kind": receipt.kind,
                "exchange_return_receipt_id": receipt.exchange_return_receipt_id,
                "sold_by_user_id": (
                    str(receipt.sold_by_user_id) if receipt.sold_by_user_id else None
                ),
                "issued_at": receipt.issued_at.isoformat(),
                "tendered_amount": (
                    str(receipt.tendered_amount) if receipt.tendered_amount is not None else None
                ),
                "change_amount": (
                    str(receipt.change_amount) if receipt.change_amount is not None else None
                ),
            },
            "order": {
                "id": order.id if order else receipt.order_id,
                "number": order.number if order else None,
                "grand_total": str(order.grand_total) if order else None,
                "discount_total": str(order.discount_total) if order else None,
                "currency": order.currency if order else None,
                "note": (order.extra or {}).get("note") if order else None,
                "fully_returned": fully_returned if receipt.kind == "sale" else None,
            },
            "lines": lines_payload,
            "tenders": [
                {"method": t.method, "amount": str(t.amount), "status": t.status} for t in tenders
            ],
        }

    @staticmethod
    async def list_receipts(session: AsyncSession, tenant_id: UUID, session_id: UUID) -> list[dict]:
        """The shift's receipts with their return state — the refund picker.

        ``returned_units``/``refunded_total`` come from the return lines of
        the order (our derived equivalent of ERPNext's "Credit Note Issued"
        marker): a sale whose units all came back shows as fully returned
        without anyone flipping a status column.
        """
        rows = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.session_id == session_id,
                    )
                    .order_by(PosReceipt.issued_at.desc(), PosReceipt.id.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return await PosReceiptReads._receipt_rows(session, tenant_id, list(rows))

    @staticmethod
    async def search_receipts(
        session: AsyncSession, tenant_id: UUID, *, q: str, limit: int = 20
    ) -> list[dict]:
        """Find an original SALE receipt across every shift, by number — the refund picker's search.

        A return does not have to happen on the shift that made the sale, so the picker cannot be
        limited to the open drawer. The return state (``returned_units`` / ``refunded_total``) is
        read from the order's whole return history, never from one shift, so the quantity still
        returnable is right whichever drawer took the earlier returns. The refund itself is still
        settled on the CURRENT shift by ``return_sale``.
        """
        term = (q or "").strip()
        if len(term) < 3:
            raise ValidationError("search needs at least 3 characters")
        if limit < 1 or limit > 50:
            raise ValidationError("limit must be between 1 and 50")
        from app.core.sql import arabic_regex

        rows = (
            (
                await session.execute(
                    select(PosReceipt)
                    .where(
                        PosReceipt.tenant_id == tenant_id,
                        PosReceipt.kind == "sale",
                        # Arabic-Indic digits and a missing dash still find the receipt.
                        PosReceipt.number.op("~*")(arabic_regex(term)),
                    )
                    .order_by(PosReceipt.issued_at.desc(), PosReceipt.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return await PosReceiptReads._receipt_rows(session, tenant_id, list(rows))

    @staticmethod
    async def _receipt_rows(
        session: AsyncSession, tenant_id: UUID, rows: list[PosReceipt]
    ) -> list[dict]:
        """Receipts as picker rows, with return state from the order's whole return history."""
        order_ids = [r.order_id for r in rows]
        returned: dict[UUID, tuple[int, Decimal]] = {}
        if order_ids:
            for order_id, qty, total in (
                await session.execute(
                    select(
                        PosReturnLine.order_id,
                        func.coalesce(func.sum(PosReturnLine.quantity), 0),
                        func.coalesce(func.sum(PosReturnLine.refund_total), 0),
                    )
                    .where(
                        PosReturnLine.tenant_id == tenant_id,
                        PosReturnLine.order_id.in_(order_ids),
                    )
                    .group_by(PosReturnLine.order_id)
                )
            ).all():
                returned[order_id] = (int(qty), to_money(total, "refunded"))
        out: list[dict] = []
        for r in rows:
            units, refunded = returned.get(r.order_id, (0, Decimal("0")))
            out.append(
                {
                    "id": r.id,
                    "number": r.number,
                    "kind": r.kind,
                    "exchange_return_receipt_id": r.exchange_return_receipt_id,
                    "order_id": r.order_id,
                    "session_id": r.session_id,
                    "issued_at": r.issued_at.isoformat(),
                    "tendered_amount": (
                        str(r.tendered_amount) if r.tendered_amount is not None else None
                    ),
                    "change_amount": (
                        str(r.change_amount) if r.change_amount is not None else None
                    ),
                    "returned_units": units if r.kind == "sale" else 0,
                    "refunded_total": str(refunded) if r.kind == "sale" else None,
                }
            )
        return out
