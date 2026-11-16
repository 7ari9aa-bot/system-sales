"""What the assistant is doing right now, written as it happens and shown to the owner.

While a question runs the owner used to see three bouncing dots and nothing else for about fifteen
seconds. The steps here are REAL: each one is written when that thing actually starts, never on a
timer, so "reading your sales" is never shown for work that has not begun. A text invented to look
busy would be a prepared reply, which this assistant never has.

Two rules keep this from ever costing an answer:

* A step is written on its OWN short session and committed at once. The turn's session is in the
  middle of a transaction the model call is part of; a commit on it would close that transaction
  (the exact bug that once made every send return 500), and a write left uncommitted could not be
  seen by the page that is polling for it.
* Writing a step can never raise. If the database refuses it, the step is dropped and the answer
  is unaffected: progress is a courtesy, the answer is the product.

The wording is a closed list in plain Arabic. A tool's own name never reaches the owner: that is
an internal word, and the shop owner is not a programmer.
"""

from __future__ import annotations

import functools
import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import text

from app.core import db as core_db
from app.core.db import bind_tenant

logger = logging.getLogger(__name__)

# Each key is a thing the assistant really does; each value is what the owner reads for it.
# There is deliberately no "writing the reply" step. The shared runner calls the model in several
# places and nothing marks the last call, so any moment picked to write it would also fire while
# the model is only deciding which tool to call, and the owner would be told a reply is being
# written when it is not. The page says it instead: when the newest step is a tool and the answer
# has not arrived, the model is composing it, which is true by construction.
STEP_TEXT: dict[str, str] = {
    "sales": "بقرا مبيعاتك",
    "stock": "بشوف المخزون",
    "finance": "بحسب المصاريف والأرباح",
    "purchasing": "بقرا المشتريات",
    "cashier": "بقرا مبيعات الكاشير",
    "orders": "بدوّر في الأوردرات",
    "customers": "بدوّر في العملاء",
    "activity": "بشوف نشاط العملاء والقنوات",
    "why": "بحلل الأسباب",
    "status": "بتأكد من حالة البيانات",
}

# The owner assistant's tools, by the step each one is. One tool now covers several reads, so the
# step comes from the parameter that picks the read; a value not listed shows no step: better
# silent than a wrong sentence.
TOOL_STEP_BY: dict[str, tuple[str, dict[str, str]]] = {
    "si_metric": (
        "mode",
        {
            "value": "sales",
            "compare": "sales",
            "split": "sales",
            "explain": "sales",
            "why": "why",
            "activity": "activity",
            "status": "status",
        },
    ),
    "si_shop": (
        "view",
        {
            "products": "sales",
            "stock": "stock",
            "cashier": "cashier",
            "order": "orders",
            "customer": "customers",
        },
    ),
    "si_finance": (
        "report",
        {"expenses": "finance", "profit": "finance", "purchasing": "purchasing"},
    ),
}


def step_for_tool(tool_name: str | None, arguments: dict | None = None) -> str | None:
    """The step key for a tool call, or None when it has no owner-facing wording."""
    picked = TOOL_STEP_BY.get(tool_name) if tool_name else None
    if picked is None:
        return None
    key, steps = picked
    value = (arguments or {}).get(key)
    return steps.get(value) if isinstance(value, str) else None


async def note_step(tenant_id: uuid.UUID, message_id: uuid.UUID, step: str) -> None:
    """Record that the assistant has started ``step`` on this answer. Never raises."""
    line = STEP_TEXT.get(step)
    if line is None:
        return
    try:
        async with core_db.get_sessionmaker()() as session:
            await bind_tenant(session, tenant_id)
            # One statement does the read, the check and the write, so two steps written close
            # together cannot overwrite each other (reading the list into Python first did exactly
            # that: the second write started from a stale copy and dropped the first). It adds the
            # line only if it is not already there, and only while the answer is still generating,
            # since a step arriving after the reply would only make the finished answer flicker.
            await session.execute(
                text(
                    "UPDATE ai_chat_messages "
                    "   SET progress = COALESCE(progress, '[]'::jsonb) "
                    "                  || to_jsonb(CAST(:line AS text)) "
                    " WHERE id = :id AND status = 'generating' "
                    "   AND NOT (COALESCE(progress, '[]'::jsonb) ? CAST(:line AS text))"
                ),
                {"id": message_id, "line": line},
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — a missed step must never cost the owner the answer
        logger.warning("chat_progress.step_unwritten message=%s step=%s", message_id, step)


# Which answer is being written right now, set by the chat turn and read by the tool wrapper. A
# tool is called deep inside the shared runner, which knows nothing about chat messages; carrying
# the answer's id in a context variable lets a tool announce itself without changing the runner or
# any handler's signature. Outside a chat turn (a scheduled job, the older /ai/sales route) it is
# None, and a tool then announces nothing.
_CURRENT_ANSWER: ContextVar[tuple[uuid.UUID, uuid.UUID] | None] = ContextVar(
    "chat_progress_answer", default=None
)


@contextmanager
def announcing_to(tenant_id: uuid.UUID, message_id: uuid.UUID):
    """Within this block, a tool that starts is written as a step on ``message_id``."""
    token = _CURRENT_ANSWER.set((tenant_id, message_id))
    try:
        yield
    finally:
        _CURRENT_ANSWER.reset(token)


async def announce(step: str) -> None:
    """Write ``step`` on the answer being produced, if there is one. Never raises."""
    current = _CURRENT_ANSWER.get()
    if current is not None:
        await note_step(current[0], current[1], step)


def with_progress(tool_name: str, handler):
    """Wrap a tool handler so that starting it writes its step first.

    The wrapper keeps the handler's own signature (``functools.wraps``), because the runner reads
    it to decide what to pass in. The step is written BEFORE the handler so the owner sees what is
    being read while it is being read, and a handler that raises still leaves its step, which is
    true: the assistant did start looking. The step is chosen from the arguments the handler was
    really called with, so a tool that covers several reads names the one it is running.
    """

    @functools.wraps(handler)
    async def wrapped(*args, **kwargs):
        step = step_for_tool(tool_name, kwargs)
        if step is not None:
            await announce(step)
        return await handler(*args, **kwargs)

    wrapped.announces_progress = True  # type: ignore[attr-defined]
    return wrapped
