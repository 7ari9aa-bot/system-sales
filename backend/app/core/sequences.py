"""Gap-free counters per (tenant, kind, year), shared by every module that numbers things.

The table is ``document_counters`` (created with the expenses module), reached here with plain
SQL so that a module needing a number (a barcode, a receipt, an expense) depends on ``core`` and
never on another domain module: routing it through ``expenses`` made the catalog a member of
that module's import cycle.

The row is locked ``FOR UPDATE`` inside the caller's transaction, so two concurrent requests can
never receive the same number and a rolled-back document gives its number back.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TAKE = text(
    """
    INSERT INTO document_counters (id, tenant_id, kind, year, last_seq)
    VALUES (:id, :tenant_id, :kind, :year, 1)
    ON CONFLICT ON CONSTRAINT uq_document_counters_tenant_kind_year
    DO UPDATE SET last_seq = document_counters.last_seq + 1, updated_at = now()
    RETURNING last_seq
    """
)


async def next_sequence(session: AsyncSession, tenant_id: UUID, kind: str, *, year: int) -> int:
    """The next whole number of a (kind, year) counter.

    ``year=0`` is the convention for a sequence that never restarts (a barcode has to stay unique
    for the life of the shop, where an invoice number starts again each January).
    """
    row = await session.execute(
        _TAKE, {"id": uuid.uuid4(), "tenant_id": tenant_id, "kind": kind, "year": year}
    )
    return int(row.scalar_one())
