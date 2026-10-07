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

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError


class ConversationBusy(DomainError):
    """Another processor holds the conversation lease.

    TRANSIENT by definition — extends DomainError directly (NOT
    ConflictError) so the worker retry classification treats it as
    retryable instead of dead-lettering the event.
    """

    code = "conversation_busy"
    http_status = 409
    retryable = True

    def __init__(self, conversation_id: uuid.UUID) -> None:
        super().__init__(
            "conversation is being processed",
            details={"conversation_id": str(conversation_id)},
        )


#: Upper bound on how long the blocking (``wait=True``) form may poll for a
#: free lease before it gives up and reports the conversation busy. The wait
#: has a deadline IN THIS PROCESS — no session-level ``lock_timeout`` is set,
#: so a plain ``pg_advisory_xact_lock`` call would hang for as long as the
#: holder's transaction lives, and an interactive request behind a stuck
#: processor would hang with it.
DEFAULT_WAIT_SECONDS = 5.0

#: Poll interval while a ``wait=True`` lease waits for the holder. Small
#: enough to feel immediate, large enough to not hammer the database.
_WAIT_POLL_SECONDS = 0.05


@asynccontextmanager
async def conversation_lease(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    wait: bool = False,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
) -> AsyncIterator[None]:
    """Transaction-scoped advisory lock keyed on the conversation.

    wait=False (default): fail fast with ConversationBusy when the lease is
    held — event goes back to the queue. wait=True polls the same try-lock
    on a bounded deadline (``wait_seconds``) and raises ConversationBusy when
    it expires, so the blocking form can never outlive its caller's patience
    (used for interactive paths).

    The lock is transaction-scoped: Postgres releases it at COMMIT/ROLLBACK,
    so an error inside the block cannot leak the lease past the failed
    transaction — the error path IS the release path.
    """
    key = int(uuid.UUID(str(conversation_id)).int % (2**63 - 1))

    async def _try_acquire() -> bool:
        row = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key) AS acquired"),
                {"key": key},
            )
        ).scalar()
        return bool(row)

    if not wait:
        # FAIL FAST: read the try-lock's actual result — False means another
        # processor holds the lease, and the caller requeues instead of
        # blocking the worker pool.
        if not await _try_acquire():
            raise ConversationBusy(conversation_id)
    else:
        # BOUNDED WAIT: poll the same try-lock until the deadline. Retrying a
        # try-lock never blocks a backend (unlike pg_advisory_xact_lock, whose
        # wait nothing in this codebase bounds), and the expiry converts the
        # timed-out wait into the same ConversationBusy the fast path raises.
        deadline = time.monotonic() + wait_seconds
        while not await _try_acquire():
            if time.monotonic() >= deadline:
                raise ConversationBusy(conversation_id)
            await asyncio.sleep(_WAIT_POLL_SECONDS)
    yield
