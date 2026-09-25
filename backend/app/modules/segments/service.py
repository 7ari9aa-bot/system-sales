"""SEGMENTS domain — one shared entity for CRM/Marketing/Analytics/AI (§82).

A segment is a visual AST/DSL definition — never free SQL from the UI:

    {"all": [
        {"field": "orders_count", "op": "gt", "value": 3},
        {"field": "lifetime_value", "op": "gt", "value": 500},
        {"field": "source", "op": "eq", "value": "instagram"},
        {"since_days": 30}
    ]}

Supported combinator: all/any/not. Operators: eq, neq, gt, gte, lt, lte,
in, contains. Field whitelists prevent arbitrary column access.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, bind_tenant
from app.core.errors import ValidationError
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin
from app.core.sql import like_pattern

_ALLOWED_FIELDS = {
    "orders_count",
    "lifetime_value",
    "last_purchase_days",
    "source",
    "is_blocked",
    "has_email",
    "has_phone",
}
_ALLOWED_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"}


class Segment(TenantMixin, TimestampMixin, Base):
    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(255))
    definition: Mapped[dict] = mapped_column(JSONB)  # the DSL AST
    is_active: Mapped[bool] = mapped_column(default=True)
    # MUST be timezone-aware: the migration created this as timestamptz
    # (b2c3d4e5f6a7). A bare mapped_column() infers a NAIVE DateTime, so
    # assigning datetime.now(UTC) here made asyncpg fail at flush with
    # "can't subtract offset-naive and offset-aware datetimes" — and because
    # nothing called evaluate() until the job runner existed, the defect sat
    # latent. See tests/test_migrations.py for the guard that now catches the
    # whole class.
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_count: Mapped[int | None] = mapped_column(nullable=True)

    __table_args__ = (Index("ix_segments_tenant_name", "tenant_id", "name"),)


def validate_dsl(node: Any) -> None:
    """Validate the DSL AST structure (whitelists, no SQL injection surface)."""
    if not isinstance(node, dict):
        raise ValidationError("segment DSL node must be an object")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        if not isinstance(node[key], list) or not node[key]:
            raise ValidationError(f"{key} must be a non-empty list")
        for child in node[key]:
            validate_dsl(child)
        extra = set(node) - {key}
        if extra:
            raise ValidationError(f"unexpected keys in combinator: {extra}")
        return
    if "not" in node:
        validate_dsl(node["not"])
        if set(node) - {"not"}:
            raise ValidationError("not must be the only key")
        return
    if "field" not in node or "op" not in node:
        raise ValidationError("condition requires field+op")
    if node["field"] not in _ALLOWED_FIELDS:
        raise ValidationError(f"field not allowed: {node['field']}")
    if node["op"] not in _ALLOWED_OPS:
        raise ValidationError(f"operator not allowed: {node['op']}")
    if "value" not in node:
        raise ValidationError("condition requires value")
    # An `in` with nothing in it is not "matches nobody": it compiles to
    # `(... IN ())`, which PostgreSQL rejects as a syntax error. The whitelist
    # validator is the documented 400 boundary (§82: "an invalid definition is
    # rejected by the whitelist compiler as a ValidationError, never a 500"),
    # so the empty list has to be refused HERE — before the compiler, before
    # the bind, before the database.
    if node["op"] == "in" and isinstance(node["value"], list) and not node["value"]:
        raise ValidationError("`in` requires at least one value")


def _field_sql(field: str) -> str:
    """Whitelisted field → SQL expression against customers + aggregates."""
    mapping = {
        "orders_count": (
            "COALESCE((SELECT count(*) FROM orders o WHERE o.customer_id = customers.id), 0)"
        ),
        "lifetime_value": "customers.lifetime_value",
        "last_purchase_days": (
            "EXTRACT(day FROM now() - COALESCE("
            "(SELECT max(o.placed_at) FROM orders o "
            "WHERE o.customer_id = customers.id), now() - interval '9999 days'))"
        ),
        "source": (
            "COALESCE((SELECT t.source FROM touchpoints t "
            "WHERE t.customer_id = customers.id "
            "ORDER BY t.created_at DESC LIMIT 1), 'direct')"
        ),
        "is_blocked": "customers.is_blocked",
        "has_email": "(customers.email IS NOT NULL)",
        "has_phone": "(customers.phone IS NOT NULL)",
    }
    if field not in mapping:
        raise ValidationError(f"field not allowed: {field}")
    return mapping[field]


def _compile_where(node: dict, params: dict) -> str:
    """Compile the DSL into a WHERE fragment with monotonic bind params.

    §M2: param names are minted sequentially (p0, p1, …) so two conditions on
    the same field can never collide and flip each other's values.
    """
    if "all" in node or "any" in node:
        joiner = " AND " if "all" in node else " OR "
        parts = [_compile_where(child, params) for child in node["all" if "all" in node else "any"]]
        return "(" + joiner.join(parts) + ")"
    if "not" in node:
        return "(NOT " + _compile_where(node["not"], params) + ")"

    # leaf condition
    field_sql = _field_sql(node["field"])
    op = node["op"]
    value = node["value"]
    # `key` is this leaf's parameter name — and, for `in`, the PREFIX of one
    # name per element. It is only bound when the SQL actually names it:
    # binding the leaf value unconditionally used to mint a `p1` holding the
    # whole list beside `p1_0`/`p1_1`, and `p1` appeared in no placeholder, so
    # asyncpg never received it (see ``Compiled.positiontup``, which is exactly
    # the argument list the driver call sends). A parameter that is computed,
    # "bound", and then dropped is a lie about what the database compared.
    key = f"p{len(params)}"

    ops = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    if op == "in":
        values = value if isinstance(value, list) else [value]
        if not values:
            # validate_dsl refuses this on every service path; this guard is
            # for the direct caller, because `(x IN ())` is a syntax error.
            raise ValidationError("`in` requires at least one value")
        marks = []
        for i, item in enumerate(values):
            item_key = f"{key}_{i}"
            params[item_key] = item
            marks.append(f":{item_key}")
        return f"({field_sql} IN ({', '.join(marks)}))"
    if op == "contains":
        # A rule's value arrives from JSON and the validator checks it exists,
        # not that it is text; `contains 5` means the substring "5".
        params[key] = like_pattern(str(value))
        return f"({field_sql} ILIKE :{key} ESCAPE '\\')"
    params[key] = value
    return f"({field_sql} {ops[op]} :{key})"


class SegmentService:
    @staticmethod
    async def create(
        session: AsyncSession, tenant_id: uuid.UUID, *, name: str, definition: dict
    ) -> Segment:
        validate_dsl(definition)
        segment = Segment(tenant_id=tenant_id, name=name, definition=definition)
        session.add(segment)
        await session.flush()
        return segment

    @staticmethod
    async def evaluate(
        session: AsyncSession, tenant_id: uuid.UUID, segment: Segment
    ) -> list[uuid.UUID]:
        """Evaluate the DSL against customers; returns matching customer ids.

        Runs under the caller's tenant GUC (RLS scopes customers).
        """
        validate_dsl(segment.definition)
        params: dict = {"t": tenant_id}
        where = _compile_where(segment.definition, params)
        # inject since_days filter as relative date if used
        sql = f"SELECT id FROM customers WHERE tenant_id = :t AND deleted_at IS NULL AND {where}"
        await bind_tenant(session, tenant_id)
        rows = (await session.execute(text(sql), params)).scalars().all()
        segment.last_evaluated_at = datetime.now(UTC)
        segment.last_count = len(rows)
        await session.flush()
        return list(rows)

    @staticmethod
    async def list_segment_customers(
        session: AsyncSession, tenant_id: uuid.UUID, segment_id: uuid.UUID
    ) -> list[uuid.UUID]:
        from sqlalchemy import select

        segment = (
            await session.execute(
                select(Segment).where(Segment.tenant_id == tenant_id, Segment.id == segment_id)
            )
        ).scalar_one_or_none()
        if segment is None:
            from app.core.errors import NotFoundError

            raise NotFoundError("segment not found")
        return await SegmentService.evaluate(session, tenant_id, segment)
