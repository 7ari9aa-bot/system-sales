"""A failed assistant turn leaves a reason in the log, and never the question or an answer.

The turn turns any failure into a bare 409 ("assistant turn failed; retry is available"), so a
failure that happened before any model call left no trace anywhere. The log line carries the
thread, the answer row and the exception TYPE; the exception text can echo request content, so
it must not be there.
"""

from __future__ import annotations

import logging

import pytest

from app.core.errors import ConflictError
from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as si_agent
from app.applications.apparel.modules.ai.chat import turns
from app.applications.apparel.modules.ai.models import AIChatMessage, AIChatThread
from tests.test_chat_progress_in_a_turn import (  # noqa: F401
    QUESTION,
    _ctx,
    _thread_with_question,
    writer_on_the_test_session,  # noqa: F401
)


class _Boom(RuntimeError):
    pass


async def test_a_failed_turn_logs_its_kind_but_not_the_question_text(
    db,
    tenant_ctx,
    monkeypatch,
    writer_on_the_test_session,  # noqa: F811
    caplog,
):
    thread = await _thread_with_question(db, tenant_ctx)
    thread_id = str(thread.id)

    async def fail(*args, **kwargs):
        raise _Boom(f"echoed request: {QUESTION}")

    monkeypatch.setattr(si_agent, "run_sales_analysis", fail)
    with caplog.at_level(logging.ERROR, logger=turns.logger.name):
        with pytest.raises(ConflictError):
            await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)

    lines = [r for r in caplog.records if "chat_turn.run_failed" in r.getMessage()]
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert "kind=_Boom" in message
    assert thread_id in message
    # the question never rides the message line (it is a log argument, not the exception text)
    assert QUESTION not in message


async def test_the_failed_row_and_the_409_are_unchanged(
    db,
    tenant_ctx,
    monkeypatch,
    writer_on_the_test_session,  # noqa: F811
):
    thread = await _thread_with_question(db, tenant_ctx)
    thread_pk = thread.id

    async def fail(*args, **kwargs):
        raise _Boom("x")

    monkeypatch.setattr(si_agent, "run_sales_analysis", fail)
    with pytest.raises(ConflictError, match="retry is available"):
        await turns.run_chat_turn(db, _ctx(tenant_ctx), thread)

    from sqlalchemy import select

    row = (
        await db.execute(
            select(AIChatMessage).where(
                AIChatMessage.thread_id == thread_pk, AIChatMessage.role == "assistant"
            )
        )
    ).scalar_one()
    assert row.status == "failed" and row.error_code == "run_failed"
    assert AIChatThread  # imported for the fixture module's models
