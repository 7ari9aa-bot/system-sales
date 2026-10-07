"""Auto-reply RAG hook tests (W0.1).

`maybe_auto_reply` used to import a non-existent
`app.modules.ai.knowledge.retrieve_relevant`; the catch-all swallowed the
ImportError and EVERY auto-reply silently ran with knowledge_context=None.
These tests drive the real hook with `search_knowledge` stubbed: the
knowledge block must reach the model call, and a retrieval failure must
degrade loudly (WARNING) without killing the reply.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.modules.ai import knowledge as ai_knowledge
from app.modules.ai.gateway import AIGateway
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, KnowledgeItem
from app.modules.ai.providers import ChatCompletionResult
from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer

REPLY = "Yes, the blue widget is in stock."
SNIPPET = "The blue widget is in stock and ships in 2 days."


async def _active_agent(db, tenant_id) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        name="Support Agent",
        model="fast",
        system_prompt="You answer customers.",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _conversation_with_inbound(db, tenant_id, body="Do you have the blue widget?"):
    customer = Customer(tenant_id=tenant_id, name="RAG Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=body,
    )
    return conversation


def _patch_chat(monkeypatch) -> dict:
    calls = {"count": 0, "messages": None}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["messages"] = messages
        return ChatCompletionResult(
            content=REPLY, tool_calls=[], tokens_in=5, tokens_out=5, raw_model="fake-model"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


def _knowledge_blocks(calls) -> list[dict]:
    return [
        m
        for m in (calls["messages"] or [])
        if m["role"] == "user" and m["content"].startswith("[Knowledge base")
    ]


async def test_auto_reply_injects_knowledge_context(db, tenant_ctx, monkeypatch):
    """Retrieval results must reach the model call as a §132 context block.

    Fails while hooks.py imports the missing retrieve_relevant: the
    ImportError is swallowed and knowledge_context is always None.
    """
    tenant_id = tenant_ctx.tenant_id
    await _active_agent(db, tenant_id)
    conversation = await _conversation_with_inbound(db, tenant_id)

    async def fake_search(session, tid, query, *, limit=5, visibility="customer_facing"):
        # §157: the auto-reply path speaks to the customer, so retrieval must
        # stay customer_facing-scoped even though the stub bypasses the DB.
        assert visibility == "customer_facing"
        item = KnowledgeItem(tenant_id=tid, title="Stock", source_type="text", content=SNIPPET)
        return [(item, 0.1)]

    monkeypatch.setattr(ai_knowledge, "search_knowledge", fake_search)
    calls = _patch_chat(monkeypatch)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert calls["count"] == 1
    blocks = _knowledge_blocks(calls)
    assert len(blocks) == 1
    assert SNIPPET in blocks[0]["content"]


async def test_auto_reply_survives_retrieval_failure_with_warning(
    db, tenant_ctx, monkeypatch, caplog
):
    """Retrieval raising must not kill the reply — but the loss must WARN."""
    tenant_id = tenant_ctx.tenant_id
    await _active_agent(db, tenant_id)
    conversation = await _conversation_with_inbound(db, tenant_id)

    async def failing_search(session, tid, query, *, limit=5, visibility="customer_facing"):
        raise RuntimeError("embedding model down")

    monkeypatch.setattr(ai_knowledge, "search_knowledge", failing_search)
    calls = _patch_chat(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.modules.ai.hooks"):
        await maybe_auto_reply(db, tenant_id, conversation.id)

    # The reply still went out...
    assert calls["count"] == 1
    outbound = (
        (
            await db.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation.id,
                    Message.direction == "outbound",
                )
            )
        )
        .scalars()
        .all()
    )
    assert [m.body for m in outbound] == [REPLY]
    # ...without knowledge context...
    assert _knowledge_blocks(calls) == []
    # ...and the loss was logged at WARNING, not silently.
    assert any(
        record.levelno == logging.WARNING and "WITHOUT knowledge context" in record.getMessage()
        for record in caplog.records
    )
