"""Configure the demo tenant's AI stack with a real provider.

    .venv/bin/python scripts/configure_ai.py

Sets (via env or prompts): GEMINI_API_KEY. Upserts model_configs
(fast/strong → gemini-3.5-flash, cheap → gemini-3.5-flash-lite;
embedding → gemini-embedding-001 @1536),
creates the sales agent with active tools, and ingests starter knowledge.
Idempotent.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa
from _bootstrap import load_settings, session_factory

from app.core.db import bind_tenant
from app.core.model_registry import Base  # noqa: F401 — full metadata for FKs
from app.modules.ai.knowledge import ingest_knowledge
from app.modules.ai.models import Agent, AgentTool, ModelConfig
from app.modules.ai.secret_backfill import set_model_config_secret
from app.modules.identity.models import Tenant

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
CHAT_MODEL = "gemini-3.5-flash"
STRONG_MODEL = "gemini-3.5-flash"
CHEAP_MODEL = "gemini-3.5-flash-lite"
EMBED_MODEL = "gemini-embedding-001"

KNOWLEDGE = [
    (
        "سياسة الشحن",
        "الشحن داخل القاهرة والجيزة 50 جنيه ويصل خلال 48 ساعة. "
        "باقي المحافظات 75 جنيه ويصل خلال 3-5 أيام عمل. "
        "الشحن مجاني للطلبات فوق 1000 جنيه.",
    ),
    (
        "سياسة الاستبدال والاسترجاع",
        "الاستبدال أو الاسترجاع متاح خلال 14 يوم من الاستلام بشرط "
        "أن يكون المنتج بحالته الأصلية. مصاريف الشحن في حالة الاسترجاع "
        "على العميل إلا في حالة عيب صناعة.",
    ),
    (
        "طرق الدفع",
        "الدفع عند الاستلام (كاش للمندوب)، أو تحويل بنكي، "
        "أو بطاقة فيزا/ماستركارد عبر رابط دفع آمن نرسله على الواتساب.",
    ),
]


async def main() -> int:
    load_settings(script="scripts/configure_ai.py")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("set GEMINI_API_KEY env var")

    async with session_factory()() as session:
        async with session.begin():
            tenant = (
                await session.execute(sa.select(Tenant).where(Tenant.slug == "demo-store"))
            ).scalar_one_or_none()
            if tenant is None:
                raise SystemExit("run scripts/seed_demo.py first")
            await bind_tenant(session, tenant.id)

            # --- model configs (upsert by tenant+alias) ---
            configs = {
                "fast": {"model": CHAT_MODEL, "config": {}},
                "strong": {"model": STRONG_MODEL, "config": {}},
                "cheap": {"model": CHEAP_MODEL, "config": {}},
                "embedding": {"model": EMBED_MODEL, "config": {"dimensions": 1536}},
            }
            for alias, spec in configs.items():
                row = (
                    await session.execute(
                        sa.select(ModelConfig).where(
                            ModelConfig.tenant_id == tenant.id, ModelConfig.alias == alias
                        )
                    )
                ).scalar_one_or_none()
                values = {
                    "provider": "gemini",
                    "model": spec["model"],
                    "config": {
                        **spec["config"],
                        "base_url": GEMINI_BASE,
                    },
                    # §68: the key lives in secret_values; the row keeps only
                    # the pointer. Never inline it into the config JSONB.
                    "secret_ref": await set_model_config_secret(session, tenant.id, alias, api_key),
                    "is_active": True,
                }
                if row is None:
                    session.add(ModelConfig(tenant_id=tenant.id, alias=alias, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            print("model_configs: fast/strong/cheap/embedding → gemini")

            # --- sales agent ---
            agent = (
                await session.execute(
                    sa.select(Agent).where(
                        Agent.tenant_id == tenant.id, Agent.name == "مساعد المبيعات"
                    )
                )
            ).scalar_one_or_none()
            if agent is None:
                agent = Agent(
                    tenant_id=tenant.id,
                    name="مساعد المبيعات",
                    model="fast",
                    system_prompt=(
                        "أنت 'مساعد المبيعات' لمتجر إلكتروني مصري. تجيب بالعامية المصرية "
                        "المهذوبة وباختصار. تساعد العميل في: أسعار المنتجات، توفر المقاسات "
                        "والمخزون، سياسة الشحن والاسترجاع، وتسجيل الطلبات. استخدم الأدوات "
                        "المتاحة للبحث عن المنتجات والأسعار والمخزون قبل ما تجاوب. لو العميل "
                        "عايز يطلب، اعمله بنود الطلب وجمع الإجمالي، ولو في منتج مش متوفر "
                        "اقترح بديل. ممنوع تخترع أسعار أو منتجات — اعتمد على نتائج الأدوات فقط."
                    ),
                    temperature=0.4,
                    is_active=True,
                )
                session.add(agent)
                await session.flush()
                print("agent created: مساعد المبيعات")

            # --- tools ---
            for tool_name in ("search_products", "get_variant_price", "check_stock"):
                existing = (
                    await session.execute(
                        sa.select(AgentTool).where(
                            AgentTool.tenant_id == tenant.id,
                            AgentTool.agent_id == agent.id,
                            AgentTool.name == tool_name,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        AgentTool(
                            tenant_id=tenant.id,
                            agent_id=agent.id,
                            name=tool_name,
                            policy={"requires_approval": False},
                            is_active=True,
                        )
                    )
            # create_order intentionally NOT enabled: human confirms payments.
            print("tools: search_products, get_variant_price, check_stock")

            # --- starter knowledge ---
            ingested = 0
            for title, content in KNOWLEDGE:
                exists = (
                    await session.execute(
                        sa.text(
                            "SELECT 1 FROM knowledge_items WHERE tenant_id = :t AND title = :title"
                        ),
                        {"t": tenant.id, "title": title},
                    )
                ).scalar_one_or_none()
                if exists is None:
                    item = await ingest_knowledge(
                        session, tenant.id, title=title, content=content, source_type="text"
                    )
                    ingested += 1
                    print(f"knowledge: {title} → {item.status}")

    if ingested == 0:
        print("knowledge: already present")
    print("\nAI CONFIGURED — run scripts/e2e_ai_test.py to verify end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
