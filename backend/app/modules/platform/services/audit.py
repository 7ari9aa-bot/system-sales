"""AuditService for platform mutations."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    request_id_contextvar,
)
from app.modules.platform.models import AuditLog


class AuditService:
    """§66 — append-only audit log writer (cross-module safe, §8).

    Every critical mutation is auditable. Modules call this instead of
    touching AuditLog directly. Cross-module writers live in
    ``app.core.audit.write_audit_row`` instead, so auditing costs no
    ``module -> platform`` edge; this class stays for platform-internal callers.
    """

    @staticmethod
    async def write(
        session: Any,
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
    ) -> AuditLog:
        # §66 lineage comes from request-scoped context (installed by the edge
        # middleware and the worker runtime), never from caller arguments — an
        # argument could lie about which request caused the write. source
        # defaults to "human" when no actor kind was set; request/correlation
        # ids stay NULL outside a request/event scope (scripts, sweeps).
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            ip=ip,
            user_agent=user_agent,
            source=actor_kind_contextvar.get() or "human",
            request_id=request_id_contextvar.get(),
            correlation_id=correlation_id_contextvar.get(),
        )
        session.add(entry)
        await session.flush()
        return entry
