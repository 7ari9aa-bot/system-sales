"""ACTIVITY feed: one timeline over the real business tables.

Nothing is copied into a second "log" table: a copy can drift from the books (a sale posted
but the log write lost). The feed is a read-only UNION over the tables that ARE the record,
so what it shows is, by construction, what happened.

Each source answers the same six questions: when, what kind, which document, how much, who,
and a one-line detail. Two traps the shapes below avoid on purpose:

* a RETURN receipt's order carries the ORIGINAL order total; the money handed back is the sum
  of its return lines (a 120.00 refund on a 590.00 order must read 120.00),
* an exchange is stored as a return receipt plus a sale receipt in one transaction, so there
  is no "exchange" kind to invent; it shows as the two real documents.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KINDS = (
    "sale",
    "return",
    "purchase",
    "supplier_return",
    "supplier_payment",
    "expense",
    "inventory",
    "shift",
)

# Every branch yields: occurred_at, kind, ref_id, doc, amount, actor_id, detail.
# The tenant filter is spelled out in each branch as well as enforced by RLS: the feed must be
# safe even if it is ever run on a connection that has not bound a tenant.
_SOURCES: dict[str, str] = {
    "sale": """
        SELECT r.issued_at AS occurred_at, 'sale' AS kind, r.id AS ref_id, r.number AS doc,
               o.grand_total AS amount, s.cashier_user_id AS actor_id,
               'فاتورة بيع' AS detail
          FROM pos_receipts r
          JOIN orders o ON o.id = r.order_id AND o.tenant_id = r.tenant_id
          LEFT JOIN pos_sessions s ON s.id = r.session_id AND s.tenant_id = r.tenant_id
         WHERE r.tenant_id = :tenant AND r.kind = 'sale'
    """,
    "return": """
        SELECT r.issued_at, 'return', r.id, r.number,
               COALESCE(SUM(l.refund_total), 0), s.cashier_user_id,
               string_agg(DISTINCT COALESCE(pr.title, v.sku, ''), ' ، ')
          FROM pos_receipts r
          LEFT JOIN pos_return_lines l ON l.receipt_id = r.id AND l.tenant_id = r.tenant_id
          LEFT JOIN product_variants v ON v.id = l.variant_id AND v.tenant_id = r.tenant_id
          LEFT JOIN products pr ON pr.id = v.product_id AND pr.tenant_id = r.tenant_id
          LEFT JOIN pos_sessions s ON s.id = r.session_id AND s.tenant_id = r.tenant_id
         WHERE r.tenant_id = :tenant AND r.kind = 'return'
         GROUP BY r.id, r.issued_at, r.number, s.cashier_user_id
    """,
    "purchase": """
        SELECT COALESCE(p.received_at, p.created_at), 'purchase', p.id, p.number, p.total,
               p.created_by_user_id, sup.name
          FROM purchase_orders p
          JOIN suppliers sup ON sup.id = p.supplier_id AND sup.tenant_id = p.tenant_id
         WHERE p.tenant_id = :tenant AND p.status = 'received'
    """,
    "supplier_return": """
        SELECT COALESCE(sr.decided_at, sr.created_at), 'supplier_return', sr.id, sr.number,
               sr.total,
               sr.created_by_user_id, sup.name || ' · ' || sr.status
          FROM supplier_returns sr
          JOIN suppliers sup ON sup.id = sr.supplier_id AND sup.tenant_id = sr.tenant_id
         WHERE sr.tenant_id = :tenant
    """,
    "supplier_payment": """
        SELECT sp.created_at, 'supplier_payment', sp.id, 'PAY-' || upper(left(sp.id::text, 8)),
               CASE WHEN sp.reverses_payment_id IS NULL THEN sp.amount ELSE -abs(sp.amount) END,
               sp.created_by_user_id,
               sup.name || CASE WHEN sp.reverses_payment_id IS NULL THEN '' ELSE ' (عكس دفعة)' END
          FROM supplier_payments sp
          JOIN suppliers sup ON sup.id = sp.supplier_id AND sup.tenant_id = sp.tenant_id
         WHERE sp.tenant_id = :tenant
    """,
    "expense": """
        SELECT e.created_at, 'expense', e.id, e.number, e.amount, e.created_by_user_id,
               e.description || CASE WHEN e.status = 'voided' THEN ' (ملغي)' ELSE '' END
          FROM expenses e
         WHERE e.tenant_id = :tenant
    """,
    "inventory": """
        SELECT m.created_at, 'inventory', m.id, 'MOV-' || m.ledger_seq::text,
               m.quantity, NULL::uuid, m.reason || ' / ' || m.direction
          FROM inventory_movements m
         WHERE m.tenant_id = :tenant
           AND m.reason NOT IN ('reservation', 'reservation_release')
    """,
    "shift": """
        SELECT x.at, 'shift', x.ref_id, x.doc, x.amount, x.actor_id, x.detail FROM (
            SELECT s.opened_at AS at, s.id AS ref_id, 'فتح وردية' AS doc, s.opening_float AS amount,
                   COALESCE(s.opened_by_user_id, s.cashier_user_id) AS actor_id, 'opened' AS detail
              FROM pos_sessions s WHERE s.tenant_id = :tenant
            UNION ALL
            SELECT s.closed_at, s.id, 'إغلاق وردية', s.counted_cash, s.closed_by_user_id,
                   'closed variance=' || COALESCE(s.variance::text, '0')
              FROM pos_sessions s WHERE s.tenant_id = :tenant AND s.closed_at IS NOT NULL
        ) x
    """,
}


def _like_literal(term: str) -> str:
    """Make a typed search a literal: `%` and `_` are characters to find, not wildcards."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_COLS = "occurred_at, kind, ref_id, doc, amount, actor_id, detail"


def _union(kinds) -> str:
    """Each branch is wrapped so its columns carry the same names whichever branches are chosen
    (an UNION takes its column names from the FIRST branch only)."""
    return "\nUNION ALL\n".join(
        f"SELECT {_COLS} FROM ({_SOURCES[k]}) AS t_{k}({_COLS})" for k in kinds
    )


@dataclass(frozen=True)
class Cursor:
    at: datetime
    ref: str

    def encode(self) -> str:
        raw = json.dumps({"at": self.at.isoformat(), "ref": self.ref}).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def decode(value: str) -> Cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(value.encode()))
            at = datetime.fromisoformat(data["at"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            return Cursor(at=at, ref=str(data["ref"]))
        except Exception as exc:  # noqa: BLE001 - any malformed cursor is the caller's error
            raise ValueError("bad cursor") from exc


class ActivityService:
    @staticmethod
    async def feed(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        kinds: tuple[str, ...] | None = None,
        actor_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        cursor: Cursor | None = None,
        limit: int = 50,
    ) -> tuple[list[dict], Cursor | None]:
        wanted = [k for k in (kinds or KINDS) if k in _SOURCES]
        if not wanted:
            return [], None
        union = _union(wanted)

        where = ["1=1"]
        params: dict = {"tenant": tenant_id, "lim": limit + 1}
        if actor_id:
            where.append("f.actor_id = :actor")
            params["actor"] = actor_id
        if date_from:
            where.append("f.occurred_at >= :dfrom")
            params["dfrom"] = date_from
        if date_to:
            where.append("f.occurred_at < :dto")
            params["dto"] = date_to
        if search and search.strip():
            where.append(
                "(f.doc ILIKE :q ESCAPE '\\' OR f.detail ILIKE :q ESCAPE '\\' "
                "OR u.full_name ILIKE :q ESCAPE '\\')"
            )
            params["q"] = f"%{_like_literal(search.strip())}%"
        if cursor:
            # Strictly after the last row seen, in (time desc, ref desc) order: no row is
            # skipped or repeated when several share the same instant.
            where.append("(f.occurred_at, f.ekey) < (:cat, :cref)")
            params["cat"] = cursor.at
            params["cref"] = cursor.ref

        sql = f"""
            SELECT f.occurred_at, f.kind, f.ref_id::text AS ref_id, f.ekey, f.doc, f.amount,
                   f.actor_id::text AS actor_id, u.full_name AS actor_name, f.detail
              FROM (SELECT *, kind || ':' || ref_id::text || ':' || doc AS ekey
                      FROM ({union}) base) f
              LEFT JOIN users u ON u.id = f.actor_id
             WHERE {" AND ".join(where)}
             ORDER BY f.occurred_at DESC, f.ekey DESC
             LIMIT :lim
        """  # noqa: S608 - only whitelisted fragments are interpolated; every value is bound
        rows = [dict(r) for r in (await session.execute(text(sql), params)).mappings()]
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = Cursor(at=rows[-1]["occurred_at"], ref=rows[-1]["ekey"]) if more and rows else None
        return rows, nxt

    @staticmethod
    async def summary(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, int]:
        """How many events of each kind in the window (the cards above the table)."""
        union = _union(KINDS)
        where = ["1=1"]
        params: dict = {"tenant": tenant_id}
        if date_from:
            where.append("f.occurred_at >= :dfrom")
            params["dfrom"] = date_from
        if date_to:
            where.append("f.occurred_at < :dto")
            params["dto"] = date_to
        sql = (  # noqa: S608 - only whitelisted fragments are interpolated; values are bound
            f"SELECT f.kind, count(*) AS n FROM ({union}) f "
            f"WHERE {' AND '.join(where)} GROUP BY f.kind"
        )
        got = {
            r["kind"]: int(r["n"]) for r in (await session.execute(text(sql), params)).mappings()
        }
        return {k: got.get(k, 0) for k in KINDS}
