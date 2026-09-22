"""§66: audit rows carry source / request_id / correlation_id lineage.

DB-backed (CI): writes through AuditService with the request-scoped
contextvars set and asserts the persisted row carries the lineage; and that
a write with no context installed defaults source to "human" and leaves the
ids NULL.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    request_id_contextvar,
)
from app.modules.platform.models import AuditLog
from app.modules.platform.service import AuditService


async def test_audit_write_carries_request_lineage(db, tenant_ctx) -> None:
    req_token = request_id_contextvar.set("req-66-test")
    cor_token = correlation_id_contextvar.set("cor-66-test")
    kind_token = actor_kind_contextvar.set("automation")
    try:
        entry = await AuditService.write(
            db,
            tenant_ctx.tenant_id,
            tenant_ctx.user.id,
            "test.lineage_check",
            "customer",
            str(uuid.uuid4()),
        )
    finally:
        request_id_contextvar.reset(req_token)
        correlation_id_contextvar.reset(cor_token)
        actor_kind_contextvar.reset(kind_token)

    assert entry.source == "automation"
    assert entry.request_id == "req-66-test"
    assert entry.correlation_id == "cor-66-test"

    row = (
        await db.execute(sa.select(AuditLog).where(AuditLog.id == entry.id))
    ).scalar_one()
    assert row.source == "automation"
    assert row.request_id == "req-66-test"
    assert row.correlation_id == "cor-66-test"


async def test_audit_write_without_context_defaults(db, tenant_ctx) -> None:
    entry = await AuditService.write(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "test.lineage_check_unscoped",
        "customer",
        str(uuid.uuid4()),
    )

    assert entry.source == "human"  # §66 default when no actor kind is set
    assert entry.request_id is None
    assert entry.correlation_id is None
