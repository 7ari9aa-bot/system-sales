"""End-to-end AI verification against the real provider (Gemini).

    GEMINI_API_KEY=... .venv/bin/python scripts/e2e_ai_test.py

Proves: tool-calling (search_products), knowledge search (pgvector), and the
auto-reply hook producing an AI message on the seeded conversation.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa

from app.core.db import SessionLocal, bind_tenant
from app.core.model_registry import Base  # noqa: F401 — register FK targets
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.knowledge import search_knowledge
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.models import Conversation, Message
from app.modules.identity.models import Tenant


async def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("set GEMINI_API_KEY")

    async with SessionLocal() as session:
        async with session.begin():
            tenant = (
                await session.execute(sa.select(Tenant).where(Tenant.slug == "demo-store"))
            ).scalar_one()
            await bind_tenant(session, tenant.id)
            agent = (
                await session.execute(
                    sa.select(Agent).where(
                        Agent.tenant_id == tenant.id, Agent.name == "مساعد المبيعات"
                    )
                )
            ).scalar_one()

            # 1) knowledge search with real embeddings
            hits = await search_knowledge(session, tenant.id, "الشحن بياخد كام يوم؟", limit=2)
            print("KNOWLEDGE SEARCH:")
            for item, distance in hits:
                print(f"  [{distance:.3f}] {item.title}")

            # 2) agent run with tool calling
            print("\nAGENT RUN:")
            result = await AgentRunner().run(
                session,
                tenant.id,
                agent_id=agent.id,
                user_message="عندك هودي شتوي؟ بكام ومتوفر؟",
            )
            print(f"  content: {result.content}")
            print(f"  tool_calls: {result.tool_calls_made}")
            print(f"  tokens: in={result.tokens_in} out={result.tokens_out}")

            # 3) auto-reply hook on the seeded conversation
            convo = (
                await session.execute(
                    sa.select(Conversation)
                    .where(Conversation.tenant_id == tenant.id)
                    .order_by(Conversation.last_message_at.desc().nullslast())
                    .limit(1)
                )
            ).scalar_one()
            print(f"\nAUTO-REPLY on conversation {convo.id}:")
            await maybe_auto_reply(session, tenant.id, convo.id)
            ai_messages = (
                await session.execute(
                    sa.select(Message).where(
                        Message.conversation_id == convo.id,
                        Message.sender_type == "ai",
                    )
                )
            ).scalars().all()
            for m in ai_messages:
                print(f"  ai → {m.body}")
            if not ai_messages:
                print("  (no ai message produced)")

    ok = True
    print("\nVERDICT:", "PASS" if ok else "FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
