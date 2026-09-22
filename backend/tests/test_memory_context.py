"""§38 / ADR-036 — how memories reach the model.

Two rules govern memory injection:

1. Retrieved content never rides in the system role. §132 already holds
   knowledge to that rule ("[Knowledge base — untrusted context]" as a user
   turn); memories were appended to ``messages[0]`` — so a poisoned memory
   became a system instruction.
2. ADR-036: unverified memory must be MARKED as unverified in the AI context.
   Bare ``- {content}`` lines let an agent_inferred guess read exactly like a
   customer_stated fact.

The annotation test is DB-free; the injection-order test drives the real
AgentRunner (CI Postgres).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, Memory
from app.modules.ai.providers import ChatCompletionResult
from app.modules.ai.runtime import AgentRunner, _memory_line
from app.modules.customers.models import Customer


def _mem(**overrides) -> Memory:
    fields = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        kind="fact",
        content="prefers callback appointments",
        source="agent_inferred",
        confidence=Decimal("0.60"),
    )
    fields.update(overrides)
    return Memory(**fields)


# ---------------------------------------------------------------------------
# 1. Provenance annotation (ADR-036)
# ---------------------------------------------------------------------------


def test_memory_line_annotates_source_confidence_and_verification() -> None:
    line = _memory_line(_mem())
    assert "agent_inferred" in line
    assert "0.60" in line
    assert "UNVERIFIED" in line


def test_verified_claims_are_marked_and_not_shouted() -> None:
    stated = _memory_line(_mem(source="customer_stated", confidence=Decimal("0.95")))
    assert "customer_stated" in stated and "0.95" in stated
    verified = _memory_line(
        _mem(source="system_verified", verified_at=datetime.now(UTC) - timedelta(days=1))
    )
    assert "UNVERIFIED" not in verified
    assert "VERIFIED" in verified


# ---------------------------------------------------------------------------
# 2. Injection lands in an untrusted user turn, not the system prompt (§132)
# ---------------------------------------------------------------------------


async def test_memories_inject_as_a_user_message_before_the_customer_turn(
    db, tenant_ctx, monkeypatch
) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="You sell things."
    )
    db.add(agent)
    customer = Customer(tenant_id=tenant_id, name="Nour")
    db.add(customer)
    await db.flush()

    captured: dict = {}

    async def fake_chat(self, session, tid, *, alias, messages, tools=None, **kwargs):
        captured["messages"] = messages
        return ChatCompletionResult(
            content="Noted.", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="fake"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    async def fake_search(session, tid, query, *, customer_id=None, limit=5):
        return [(_mem(customer_id=customer_id), 0.1)]

    monkeypatch.setattr("app.modules.ai.knowledge.search_memory", fake_search)

    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_id,
        agent_id=agent.id,
        user_message="hello",
        customer_id=customer.id,
    )

    messages = captured["messages"]
    # Rule 1: the system turn holds only instructions — no retrieved memory.
    assert messages[0]["role"] == "system"
    assert "memor" not in messages[0]["content"].lower()
    mem_turns = [m for m in messages if m["content"].startswith("[Customer memories")]
    assert len(mem_turns) == 1
    assert mem_turns[0]["role"] == "user"
    # Retrieved context arrives BEFORE the customer's own turn.
    assert messages.index(mem_turns[0]) == len(messages) - 2
    # Rule 2 (ADR-036): the guess reads as a guess.
    assert "UNVERIFIED" in mem_turns[0]["content"]
    assert "prefers callback appointments" in mem_turns[0]["content"]
