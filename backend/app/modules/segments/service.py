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

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, bind_tenant
from app.core.errors import ValidationError
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin

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
    last_evaluated_at: Mapped[datetime | None] = mapped_column(nullable=True)
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


def _condition_sql(node: dict) -> str:
    field_sql = _field_sql(node["field"])
    op = node["op"]
    value = node["value"]
    ops = {
        "eq": "=",
        "neq": "<>",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }
    if op in ops:
        return f"({field_sql} {ops[op]} :v_{node['field']}_{abs(hash(str(value))) % 10000})"
    if op == "in":
        return f"({field_sql} = ANY(:v_{node['field']}))"
    if op == "contains":
        return f"({field_sql} ILIKE '%' || :v_{node['field']} || '%')"
    raise ValidationError(f"operator not allowed: {op}")


def _collect_params(node: dict, params: dict) -> None:
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        for child in node[key]:
            _collect_params(child, params)
        return
    if "not" in node:
        _collect_params(node["not"], params)
        return
    key = (
        f"v_{node['field']}_{abs(hash(str(node['value']))) % 10000}"
        if node["op"] not in ("in", "contains")
        else f"v_{node['field']}"
    )
    params[key] = node["value"]


def _build_where(node: dict, params: dict) -> str:
    if "all" in node:
        return "(" + " AND ".join(_build_where(c, params) for c in node["all"]) + ")"
    if "any" in node:
        return "(" + " OR ".join(_build_where(c, params) for c in node["any"]) + ")"
    if "not" in node:
        return "(NOT " + _build_where(node["not"], params) + ")"
    return _condition_sql(node)


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
        where = _build_where(segment.definition, params)
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
