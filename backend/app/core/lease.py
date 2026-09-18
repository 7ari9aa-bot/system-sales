"""Conversation serialization (spec §126, ADR-006).

Rule: at most ONE state-mutating processor (AI run / agent reply / automation)
may act on a conversation at a time. Implemented with a Postgres transaction-
scoped advisory lock on the conversation id — no Redis dependency for
correctness, released automatically at COMMIT/ROLLBACK.

Usage inside a transaction:

    async with conversation_lease(session, conversation_id):
        ...mutating work (AI run, outbound message)...

If the lease is held elsewhere, raises ConversationBusy (caller may requeue
the event instead of blocking the worker pool).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError


class ConversationBusy(ConflictError):
    """Another processor holds the conversation lease."""

    def __init__(self, conversation_id: uuid.UUID) -> None:
        super().__init__(
            "conversation is being processed",
            details={"conversation_id": str(conversation_id)},
        )


@asynccontextmanager
async def conversation_lease(
    session: AsyncSession, conversation_id: uuid.UUID, *, wait: bool = False
) -> AsyncIterator[None]:
    """Transaction-scoped advisory lock keyed on the conversation.

    wait=False (default): fail fast with ConversationBusy when the lease is
    held — event goes back to the queue. wait=True blocks (bounded by PG
    lock_timeout, used for interactive paths).
    """
    key = int(uuid.UUID(str(conversation_id)).int % (2**63 - 1))
    lock_fn = "pg_advisory_xact_lock(:key)" if wait else "pg_try_advisory_xact_lock(:key)"
    row = (
        await session.execute(text(f"SELECT {lock_fn} AS acquired"), {"key": key})
    ).scalar()
    if not row:
        raise ConversationBusy(conversation_id)
    yield
