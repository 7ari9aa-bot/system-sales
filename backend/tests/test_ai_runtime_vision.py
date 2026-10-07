"""AgentRunner vision/grounding tests (§7.1.3, §12, §13) — real DB, fake model.

Covers the runner-side M1 behaviors: the current user turn becomes multimodal
content parts when the newest inbound message carries a photo (older photos
stay text markers), grounding v1 (one regeneration, then hand over), and
server-side media collection with the four-image cap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.catalog.models import Product, ProductImage, ProductVariant
from app.modules.conversations import models as conv_models
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer


def _patch_gateway(monkeypatch, results: list[ChatCompletionResult]) -> dict:
    calls = {"count": 0, "list": []}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["list"].append({"messages": messages, "tools": tools})
        return results[min(calls["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


def _patch_signed_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.storage.get_storage",
        lambda: SimpleNamespace(signed_url=lambda key, **kw: f"https://signed.test/{key}"),
    )


async def _agent_with(db, tenant_id, name: str) -> Agent:
    agent = Agent(tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="You sell.")
    db.add(agent)
    await db.flush()
    db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name, policy={}))
    await db.flush()
    return agent


async def _seed_variant(db, tenant_id) -> ProductVariant:
    product = Product(
        tenant_id=tenant_id,
        title="Blue Widget",
        slug=f"bw-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        id=uuid.UUID("abcdefabcdefabcdefabcdefabcdefab"),
        tenant_id=tenant_id,
        product_id=product.id,
        # FIXED sku: a random hex could contain the very numeral a test
        # asserts is ungrounded (e.g. "99"), flipping the grounding verdict.
        sku="BW-TEST01",
        title="Blue Widget M",
        price=Decimal("25.50"),
    )
    db.add(variant)
    await db.flush()
    return variant


async def _conversation_with_inbound_image(
    db, tenant_id, *, storage_key: str, created_at, body: str | None = None
):
    customer = Customer(tenant_id=tenant_id, name="Vision Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = conv_models.Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=body,
        content_type="image" if not body else "text",
        media_type=None if body else "image",
        created_at=created_at,
    )
    db.add(message)
    await db.flush()
    db.add(
        conv_models.Attachment(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message_id=message.id,
            storage_key=storage_key,
            mime_type="image/png",
        )
    )
    await db.flush()
    return conversation, message


def _content_parts(messages: list[dict]) -> list[dict]:
    parts: list[dict] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            parts.extend(content)
    return parts


def _text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return " ".join(part.get("text", "") for part in content if part.get("type") == "text")


async def test_current_turn_rides_the_photo_as_content_parts(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    conversation, _message = await _conversation_with_inbound_image(
        db,
        tenant_id,
        storage_key="photos/new.png",
        created_at=datetime.now(UTC),
    )
    _patch_signed_urls(monkeypatch)
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content="ده abaya", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            )
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        user_message="ده ايه؟",
    )

    assert result.content == "ده abaya"
    last_user = calls["list"][0]["messages"][-1]
    assert last_user["role"] == "user" and isinstance(last_user["content"], list)
    assert {"type": "text", "text": "ده ايه؟"} in last_user["content"]
    assert {
        "type": "image_url",
        "image_url": {"url": "https://signed.test/photos/new.png"},
    } in last_user["content"]


async def test_older_photos_stay_text_markers(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    now = datetime.now(UTC)
    conversation, _newest = await _conversation_with_inbound_image(
        db, tenant_id, storage_key="photos/old.png", created_at=now - timedelta(minutes=5)
    )
    # A second, NEWER inbound image — the one that should ride the turn.
    message = conv_models.Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=None,
        content_type="image",
        media_type="image",
        created_at=now,
    )
    db.add(message)
    await db.flush()
    db.add(
        conv_models.Attachment(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message_id=message.id,
            storage_key="photos/new.png",
            mime_type="image/png",
        )
    )
    await db.flush()

    _patch_signed_urls(monkeypatch)
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content="ok", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            )
        ],
    )

    await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, conversation_id=conversation.id, user_message="؟"
    )

    parts = _content_parts(calls["list"][0]["messages"])
    image_parts = [p for p in parts if p.get("type") == "image_url"]
    assert len(image_parts) == 1  # history cannot flood the prompt with photos
    assert image_parts[0]["image_url"]["url"].endswith("photos/new.png")
    marker_turns = [
        m for m in calls["list"][0]["messages"] if m["role"] == "user" and "sent image" in _text(m)
    ]
    assert marker_turns, "the older photo stays a text marker (§7.1.3)"


async def test_grounded_reply_needs_no_regeneration(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    await _seed_variant(db, tenant_id)
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="search_products", arguments={"query": "widget"})
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            ChatCompletionResult(
                content="السعر 25.5 جنيه", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="كام؟"
    )

    assert result.content == "السعر 25.5 جنيه"
    assert calls["count"] == 2  # tool turn + answer; no corrective regeneration


async def test_ungrounded_reply_regenerates_once_with_tools_disabled(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    await _seed_variant(db, tenant_id)
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="search_products", arguments={"query": "widget"})
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            ChatCompletionResult(
                content="السعر 99 جنيه", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
            ChatCompletionResult(
                content="السعر 25.5 جنيه", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="كام؟"
    )

    # The correction replaced the draft and it grounded cleanly.
    assert result.content == "السعر 25.5 جنيه"
    assert result.guardrail_reason != "grounding_failed"
    assert calls["count"] == 3
    regen = calls["list"][2]
    assert regen["tools"] is None  # no tools: the correction reuses facts only
    assert "ONLY numbers the tools returned" in _text(regen["messages"][-1])


async def test_ungrounded_twice_hands_over(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    await _seed_variant(db, tenant_id)
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="c1", name="search_products", arguments={"query": "widget"})
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            ChatCompletionResult(
                content="السعر 99 جنيه", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
            ChatCompletionResult(
                content="للأسف 99 برضه", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="كام؟"
    )

    assert result.content is None
    assert result.guardrail_decision == "block"
    assert result.guardrail_reason == "grounding_failed"
    assert calls["count"] == 3  # exactly ONE regeneration, then hand over


async def test_no_tool_results_skips_grounding(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "search_products")
    calls = _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content="عندنا 5 ألوان", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            )
        ],
    )

    await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="كام لون؟"
    )

    # The unsourced-claim gate owns the no-tool-results case — the grounding
    # controller must not spend a regeneration here.
    assert calls["count"] == 1


async def test_media_collected_server_side_with_cap_and_shown_ids(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with(db, tenant_id, "resolve_product_media")
    product = Product(tenant_id=tenant_id, title="Abaya", slug=f"abaya-{uuid.uuid4().hex[:8]}")
    db.add(product)
    await db.flush()
    images = []
    for position in range(6):
        image = ProductImage(
            tenant_id=tenant_id,
            product_id=product.id,
            url=f"https://cdn.test/{position}.png",
            alt=f"صورة {position}",
            position=position,
        )
        db.add(image)
        images.append(image)
    await db.flush()

    _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="resolve_product_media",
                        arguments={"product_id": str(product.id), "selection": "all"},
                    )
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            ChatCompletionResult(
                content="اتفضل الصور", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            ),
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="وريني الصور"
    )

    # Cap: six requested, four delivered — in gallery position order.
    assert [m["image_url"] for m in result.media] == [f"https://cdn.test/{p}.png" for p in range(4)]
    assert all(set(m) == {"image_id", "image_url", "alt"} for m in result.media)
    assert result.shown_product_ids == [str(product.id)]
