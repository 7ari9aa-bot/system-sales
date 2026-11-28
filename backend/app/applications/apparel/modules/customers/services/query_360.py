"""Customer 360 read-model query (§137)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError


class Customer360Query:
    """§137: read-optimized Customer 360 view.

    A single get_360() call assembles the customer's 360° profile using
    raw SQL (not full ORM loads) so the dashboard drawer fetches everything
    in one round-trip without hydrating relationships.
    """

    @staticmethod
    async def get_360(session: AsyncSession, tenant_id: UUID, customer_id: UUID) -> dict:
        """Return a dict with customer info, recent orders, conversations,
        lifetime_value, and memories — all read-optimized."""
        customer_row = (
            await session.execute(
                text(
                    "SELECT id, name, phone, email, is_blocked, "
                    "lifetime_value, created_at, updated_at "
                    "FROM customers "
                    "WHERE tenant_id = :t AND id = :cid AND deleted_at IS NULL"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).one_or_none()
        if customer_row is None:
            raise NotFoundError(f"customer {customer_id} not found")
        customer_info = dict(customer_row._mapping)

        order_rows = (
            await session.execute(
                text(
                    "SELECT id, number, status, grand_total, currency, "
                    "placed_at, created_at "
                    "FROM orders "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 10"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        recent_orders = [dict(r._mapping) for r in order_rows]

        conv_rows = (
            await session.execute(
                text(
                    "SELECT id, channel, status, unread_count, created_at "
                    "FROM conversations "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        recent_conversations = [dict(r._mapping) for r in conv_rows]

        mem_rows = (
            await session.execute(
                text(
                    "SELECT id, kind, content, source, confidence, created_at "
                    "FROM memories "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        memories = [dict(r._mapping) for r in mem_rows]

        return {
            "customer": customer_info,
            "recent_orders": recent_orders,
            "recent_conversations": recent_conversations,
            # §47/ADR-053: the SAME column `customers/router.py::_customer_summary`
            # and `timeline.py` already ship as `str(Decimal)`. The `or` keeps the
            # money scale on a zero row so this reader never answers "0" where the
            # human read answers "0.00"; it is a float-free coercion, not a second
            # money rule.
            "lifetime_value": str(customer_info.get("lifetime_value") or Decimal("0.00")),
            "memories": memories,
        }
