"""CUSTOMER 360 read model (spec W5 §97-104).

Composes one customer's record across modules — profile, orders, payments,
conversations, tasks — plus a single merged chronological timeline.

This is a READ-ONLY projection: it never writes, never mutates a domain
entity, and every query is tenant-scoped. It exists because the record page
otherwise needs 5 round trips and the browser would have to merge and sort
timelines client-side, which cannot page correctly.

The orders/tasks/conversation rows are read with parameter-bound SQL rather
than by importing ``orders.models`` / ``operations.models``: this is exactly
the cross-module read-model the boundary ratchet exists to route around, and
it is the same answer ``OrderService._recompute_lifetime_value`` gives in the
other direction — a projection reads columns, it does not couple to another
domain's mapped classes. Every statement stays tenant-filtered twice over
(``WHERE tenant_id`` plus the RLS policy on the bound GUC).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import CustomerEvent
from app.modules.customers.service import CustomerService

# Per-section caps. The 360 page shows a preview of each section; the full
# lists live behind their own paginated endpoints.
DEFAULT_LIMIT = 20
DEFAULT_TIMELINE_LIMIT = 60

# Order states that still represent committed value.
_NON_COMMITTED_ORDER_STATUSES = ("draft", "cancelled")

# Payment states that mean money actually arrived.
_SETTLED_PAYMENT_STATUSES = ("captured", "partially_refunded", "refunded")


def _dec(value: Any) -> Decimal:
    """Normalise a DB numeric (Decimal | float | None) for arithmetic."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _bind_in(params: dict[str, object], prefix: str, values: tuple[str, ...]) -> str:
    """Register ``values`` in ``params`` and return their bind list.

    ``:prefix_0, :prefix_1, …`` — so an ``IN``/``NOT IN`` list is built from the
    module's own status vocabulary without ever interpolating a string into SQL.
    """
    names = [f"{prefix}_{i}" for i in range(len(values))]
    params.update(dict(zip(names, values, strict=True)))
    return ", ".join(f":{name}" for name in names)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_utc(value: datetime | None) -> datetime | None:
    """Sort keys must be tz-aware and comparable.

    Columns are DateTime(timezone=True) so Postgres returns aware datetimes,
    but a naive value here would raise on comparison against an aware one.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class Customer360Service:
    """Builds the composed customer record."""

    @staticmethod
    async def build(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        limit: int = DEFAULT_LIMIT,
        timeline_limit: int = DEFAULT_TIMELINE_LIMIT,
    ) -> dict:
        # Raises NotFoundError when the customer does not exist in this tenant.
        customer = await CustomerService.get(session, tenant_id, customer_id)

        tags = await CustomerService.list_tags(session, tenant_id, customer_id)
        identities = await CustomerService.list_identities(session, tenant_id, customer_id)
        addresses = await CustomerService.list_addresses(session, tenant_id, customer_id)
        notes = await CustomerService.list_notes(session, tenant_id, customer_id)
        events = await CustomerService.list_events(
            session, tenant_id, customer_id, limit=timeline_limit
        )

        orders = await Customer360Service._orders(session, tenant_id, customer_id, limit)
        conversations = await Customer360Service._conversations(
            session, tenant_id, customer_id, limit
        )
        tasks = await Customer360Service._tasks(session, tenant_id, customer_id, limit)
        payments = await Customer360Service._payments(session, tenant_id, customer_id)

        timeline = Customer360Service._merge_timeline(
            events=events,
            orders=orders,
            conversations=conversations,
            notes=notes,
            tasks=tasks,
            limit=timeline_limit,
        )

        return {
            "customer": {
                "id": str(customer.id),
                "name": customer.name,
                "phone": customer.phone,
                "email": customer.email,
                "locale": customer.locale,
                "lifetime_value": str(_dec(customer.lifetime_value)),
                "is_blocked": customer.is_blocked,
                "extra": customer.extra or {},
                "deleted_at": _iso(customer.deleted_at),
                "created_at": _iso(customer.created_at),
                "updated_at": _iso(customer.updated_at),
            },
            "tags": [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags],
            "identities": [
                {"id": str(i.id), "channel": i.channel, "external_id": i.external_id}
                for i in identities
            ],
            "addresses": [
                {
                    "id": str(a.id),
                    "label": a.label,
                    "line1": a.line1,
                    "line2": a.line2,
                    "city": a.city,
                    "region": a.region,
                    "postal_code": a.postal_code,
                    "country": a.country,
                    "is_default": a.is_default,
                }
                for a in addresses
            ],
            "notes": [
                {
                    "id": str(n.id),
                    "body": n.body,
                    "author_user_id": str(n.author_user_id) if n.author_user_id else None,
                    "created_at": _iso(n.created_at),
                }
                for n in notes
            ],
            "orders": orders,
            "conversations": conversations,
            "tasks": tasks,
            "payments": payments,
            "stats": Customer360Service._stats(
                orders=orders,
                conversations=conversations,
                tasks=tasks,
                payments=payments,
                events=events,
            ),
            "timeline": timeline,
        }

    # ------------------------------------------------------------ sections --

    @staticmethod
    async def _orders(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, limit: int
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    "SELECT id, number, status, currency, grand_total, channel, "
                    "placed_at, created_at "
                    "FROM orders "
                    "WHERE tenant_id = :tenant_id AND customer_id = :customer_id "
                    "ORDER BY created_at DESC, id DESC "
                    "LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "customer_id": customer_id, "limit": limit},
            )
        ).all()
        return [
            {
                "id": str(o.id),
                "number": o.number,
                "status": o.status,
                "currency": o.currency,
                "grand_total": str(_dec(o.grand_total)),
                "channel": o.channel,
                "placed_at": _iso(o.placed_at),
                "created_at": _iso(o.created_at),
            }
            for o in rows
        ]

    @staticmethod
    async def _conversations(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, limit: int
    ) -> list[dict]:
        # §137: the inbox read model is the one place a conversation list is
        # assembled. It used to be ``ConversationService.list_inbox`` — a write
        # service doing this join — which also meant this projection paid two
        # statements for a page and could never see a message preview.
        from app.modules.conversations.inbox import InboxQuery

        rows = await InboxQuery.page(session, tenant_id, customer_id=customer_id, limit=limit)
        return [
            {
                "id": c["id"],
                "channel": c["channel"],
                "status": c["status"],
                "unread_count": c["unread_count"],
                "assignee_user_id": c["assignee_user_id"],
                "last_message_at": c["last_message_at"],
                "created_at": c["created_at"],
            }
            for c in rows
        ]

    @staticmethod
    async def _tasks(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, limit: int
    ) -> list[dict]:
        rows = (
            await session.execute(
                text(
                    "SELECT id, title, status, priority, source, assignee_user_id, "
                    "due_date, created_at "
                    "FROM tasks "
                    "WHERE tenant_id = :tenant_id "
                    "AND related_entity_type = 'customer' "
                    "AND related_entity_id = :customer_id "
                    "ORDER BY created_at DESC, id DESC "
                    "LIMIT :limit"
                ),
                {"tenant_id": tenant_id, "customer_id": customer_id, "limit": limit},
            )
        ).all()
        return [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "source": t.source,
                "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
                "due_date": _iso(t.due_date),
                "created_at": _iso(t.created_at),
            }
            for t in rows
        ]

    @staticmethod
    async def _payments(session: AsyncSession, tenant_id: UUID, customer_id: UUID) -> dict:
        """Money actually collected, refunded, and still owed.

        Payments hang off orders (no direct customer FK), so both aggregates
        join through the customer's orders.

        The status vocabularies stay the module constants above and are passed
        as binds, so this projection cannot drift from the words the domains
        actually write.
        """
        binds: dict[str, object] = {"tenant_id": tenant_id, "customer_id": customer_id}
        non_committed = _bind_in(binds, "nc", _NON_COMMITTED_ORDER_STATUSES)
        settled = _bind_in(binds, "st", _SETTLED_PAYMENT_STATUSES)

        money_row = (
            await session.execute(
                text(
                    "SELECT COALESCE("
                    "SUM(grand_total) FILTER (WHERE status NOT IN ("
                    f"{non_committed}"
                    ")), 0) AS committed_total, "
                    "MIN(currency) AS currency "
                    "FROM orders "
                    "WHERE tenant_id = :tenant_id AND customer_id = :customer_id"
                ),
                binds,
            )
        ).one()

        paid_row = (
            await session.execute(
                text(
                    "SELECT COALESCE("
                    "SUM(p.amount) FILTER (WHERE p.status IN ("
                    f"{settled}"
                    ")), 0) AS paid_total, "
                    "COUNT(p.id) AS payment_count "
                    "FROM order_payments AS p "
                    "JOIN orders AS o ON o.id = p.order_id "
                    "WHERE p.tenant_id = :tenant_id "
                    "AND o.tenant_id = :tenant_id "
                    "AND o.customer_id = :customer_id"
                ),
                binds,
            )
        ).one()

        refunded_total = (
            await session.execute(
                text(
                    "SELECT COALESCE("
                    "SUM(r.amount) FILTER (WHERE r.status = 'processed'), 0) "
                    "FROM refunds AS r "
                    "JOIN order_payments AS p ON p.id = r.payment_id "
                    "JOIN orders AS o ON o.id = p.order_id "
                    "WHERE r.tenant_id = :tenant_id "
                    "AND p.tenant_id = :tenant_id "
                    "AND o.tenant_id = :tenant_id "
                    "AND o.customer_id = :customer_id"
                ),
                binds,
            )
        ).scalar_one()

        orders_total = money_row.committed_total
        currency_code = money_row.currency
        paid_total = paid_row.paid_total
        payment_count = paid_row.payment_count

        committed_total = _dec(orders_total)
        collected = _dec(paid_total)
        returned = _dec(refunded_total)
        net_collected = collected - returned

        if currency_code is None:
            # No orders yet: the tenant's own currency is the only honest label
            # for a row of zeros (§47 — it was a hard-coded "EGP" before, so a
            # SAR shop's empty money card read as Egyptian).
            from app.core.tenancy import resolve_tenant_currency

            currency_code = await resolve_tenant_currency(session, tenant_id)

        return {
            "currency": currency_code,
            "orders_total": str(committed_total),
            "paid_total": str(collected),
            "refunded_total": str(returned),
            "net_collected": str(net_collected),
            "outstanding": str(committed_total - net_collected),
            "payment_count": int(payment_count or 0),
        }

    # ------------------------------------------------------------ timeline --

    @staticmethod
    def _merge_timeline(
        *,
        events: list[CustomerEvent],
        orders: list[dict],
        conversations: list[dict],
        notes: list,
        tasks: list[dict],
        limit: int,
    ) -> list[dict]:
        """One newest-first stream of everything that happened to a customer."""
        entries: list[dict] = []

        for e in events:
            entries.append(
                {
                    "kind": "event",
                    "at": _iso(e.created_at),
                    "title": e.event_type,
                    "subtitle": None,
                    "ref_id": str(e.id),
                    "meta": e.payload or {},
                }
            )

        for o in orders:
            entries.append(
                {
                    "kind": "order",
                    "at": o.get("placed_at") or o.get("created_at"),
                    "title": o.get("number"),
                    "subtitle": o.get("status"),
                    "ref_id": o.get("id"),
                    "meta": {
                        "grand_total": o.get("grand_total"),
                        "currency": o.get("currency"),
                    },
                }
            )

        for c in conversations:
            entries.append(
                {
                    "kind": "conversation",
                    "at": c.get("last_message_at") or c.get("created_at"),
                    "title": c.get("channel"),
                    "subtitle": c.get("status"),
                    "ref_id": c.get("id"),
                    "meta": {"unread_count": c.get("unread_count")},
                }
            )

        for n in notes:
            entries.append(
                {
                    "kind": "note",
                    "at": _iso(n.created_at),
                    "title": "note",
                    "subtitle": None,
                    "ref_id": str(n.id),
                    "meta": {"body": n.body},
                }
            )

        for t in tasks:
            entries.append(
                {
                    "kind": "task",
                    "at": t.get("created_at"),
                    "title": t.get("title"),
                    "subtitle": t.get("status"),
                    "ref_id": t.get("id"),
                    "meta": {"priority": t.get("priority"), "source": t.get("source")},
                }
            )

        # Undated rows cannot be ordered, so they are excluded from the stream.
        dated = [e for e in entries if e["at"]]

        def _key(entry: dict) -> tuple[datetime, str]:
            parsed = datetime.fromisoformat(entry["at"])
            return (_as_utc(parsed) or datetime.min.replace(tzinfo=UTC), entry["ref_id"] or "")

        dated.sort(key=_key, reverse=True)
        return dated[:limit]

    # --------------------------------------------------------------- stats --

    @staticmethod
    def _stats(
        *,
        orders: list[dict],
        conversations: list[dict],
        tasks: list[dict],
        payments: dict,
        events: list[CustomerEvent],
    ) -> dict:
        open_tasks = sum(1 for t in tasks if t.get("status") in ("todo", "in_progress"))
        unread = sum(int(c.get("unread_count") or 0) for c in conversations)
        last_order_at = max(
            (o.get("created_at") for o in orders if o.get("created_at")),
            default=None,
        )
        last_message_at = max(
            (c.get("last_message_at") for c in conversations if c.get("last_message_at")),
            default=None,
        )
        return {
            "orders_shown": len(orders),
            "conversations_shown": len(conversations),
            "tasks_shown": len(tasks),
            "open_tasks": open_tasks,
            "unread_messages": unread,
            "event_count": len(events),
            "net_collected": payments.get("net_collected"),
            "outstanding": payments.get("outstanding"),
            "last_order_at": last_order_at,
            "last_message_at": last_message_at,
        }
