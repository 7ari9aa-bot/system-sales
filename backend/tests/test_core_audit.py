"""``app.core.audit.write_audit_row`` — the cross-module §66 audit writer.

DB-backed (CI): writes an ``audit_logs`` row through the core function and reads
it back, asserting the persisted columns and the §66 lineage (source / request_id
/ correlation_id) taken from the request contextvars match what the platform ORM
writer produced. Also pins the trap the ORM path hid: on the ``text()`` insert a
``None`` before/after must stay SQL NULL, never the JSON string ``"null"``.

Skips locally without ``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_row
from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    request_id_contextvar,
)
from app.modules.platform.models import AuditLog


def _row_query(resource_id: str):
    return sa.select(AuditLog).where(AuditLog.resource_id == resource_id)


async def test_write_audit_row_persists_columns_and_lineage(db: AsyncSession, tenant_ctx) -> None:
    req = request_id_contextvar.set("req-core")
    cor = correlation_id_contextvar.set("cor-core")
    kind = actor_kind_contextvar.set("ai")
    try:
        resource_id = str(uuid.uuid4())
        await write_audit_row(
            db,
            tenant_ctx.tenant_id,
            tenant_ctx.user.id,
            "core.test_action",
            "customer",
            resource_id,
            before={"v": 1},
            after={"v": 2},
            ip="203.0.113.9",
            user_agent="pytest",
        )
    finally:
        request_id_contextvar.reset(req)
        correlation_id_contextvar.reset(cor)
        actor_kind_contextvar.reset(kind)

    row = (await db.execute(_row_query(resource_id))).scalar_one()
    assert row.tenant_id == tenant_ctx.tenant_id
    assert row.actor_user_id == tenant_ctx.user.id
    assert row.action == "core.test_action"
    assert row.resource_type == "customer"
    assert row.before == {"v": 1}
    assert row.after == {"v": 2}
    assert row.ip == "203.0.113.9"
    assert row.user_agent == "pytest"
    # §66 lineage comes from context, not arguments.
    assert row.source == "ai"
    assert row.request_id == "req-core"
    assert row.correlation_id == "cor-core"


async def test_write_audit_row_defaults_source_human(db: AsyncSession, tenant_ctx) -> None:
    resource_id = str(uuid.uuid4())
    await write_audit_row(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "core.no_ctx",
        "customer",
        resource_id,
    )
    row = (await db.execute(_row_query(resource_id))).scalar_one()
    assert row.source == "human"
    assert row.request_id is None
    assert row.correlation_id is None


async def test_write_audit_row_none_jsonb_stays_sql_null(db: AsyncSession, tenant_ctx) -> None:
    """A None before/after must be SQL NULL, not the JSON literal ``"null"``.

    The ORM JSON type turned a Python ``None`` into a NULL column for free; on a
    ``text()`` insert an accidental ``json.dumps(None)`` would store the four-byte
    JSON value ``null`` instead, which reads back as ``None`` in Python but is a
    different thing in the database. Asserted at the SQL level to catch it.
    """
    resource_id = str(uuid.uuid4())
    await write_audit_row(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "core.null_jsonb",
        "customer",
        resource_id,
    )
    flags = (
        await db.execute(
            sa.text(
                "SELECT before IS NULL AS b_null, after IS NULL AS a_null "
                "FROM audit_logs WHERE resource_id = :rid"
            ),
            {"rid": resource_id},
        )
    ).one()
    assert flags.b_null is True
    assert flags.a_null is True


async def test_write_audit_row_returns_none(db: AsyncSession, tenant_ctx) -> None:
    result = await write_audit_row(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "core.returns_none",
        "customer",
        str(uuid.uuid4()),
    )
    assert result is None
