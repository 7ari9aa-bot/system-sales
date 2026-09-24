"""§66 audit writer, shared by every module (core capability, not a domain).

Auditing is cross-cutting: a mutation in ``conversations``, ``customers``,
``identity``, ``privacy``, ``catalog`` or ``orders`` all appends a row to
``audit_logs``. Each of those used to reach ``platform.service.AuditService`` to
do it, paying one cross-module edge per caller for logic that is not
platform-specific. This module is the single parameter-bound INSERT; importing
it from ``app.core`` couples nothing to another domain's tables.

``audit_logs`` is under FORCE RLS, so the INSERT only succeeds on a session whose
tenant GUC is already bound — every caller runs inside such a session. The writer
deliberately inherits that session rather than binding one of its own.

§66 lineage (``source``/``request_id``/``correlation_id``) is read from the
request-scoped contextvars installed by the edge middleware and the worker
runtime, never from caller arguments: an argument could lie about which request
caused the write. ``source`` defaults to "human" when no actor kind is set; the
ids stay NULL outside a request/event scope (scripts, sweeps).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    request_id_contextvar,
)


async def write_audit_row(
    session,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_logs (id, tenant_id, actor_user_id, action, "
            "resource_type, resource_id, before, after, ip, user_agent, source, "
            "request_id, correlation_id) VALUES (:id, :tenant_id, "
            ":actor_user_id, :action, :resource_type, :resource_id, "
            "CAST(:before AS jsonb), CAST(:after AS jsonb), :ip, :user_agent, "
            ":source, :request_id, :correlation_id)"
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "actor_user_id": actor_user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "before": None if before is None else json.dumps(before),
            "after": None if after is None else json.dumps(after),
            "ip": ip,
            "user_agent": user_agent,
            "source": actor_kind_contextvar.get() or "human",
            "request_id": request_id_contextvar.get(),
            "correlation_id": correlation_id_contextvar.get(),
        },
    )
