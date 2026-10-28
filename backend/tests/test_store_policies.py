"""The store's basic policies: written by the merchant, read by the customer agent.

A policy is a knowledge row, so what the merchant saves is exactly what ``get_store_info``
hands the agent. These run against the real database; only the embedding provider is
replaced.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.core.errors import ValidationError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai import policies
from app.modules.ai.models import KnowledgeItem
from app.modules.ai.providers import EmbeddingProvider
from app.modules.ai.tools import get_tool

VECTOR_DIM = 1536


class _NoModelSettings:
    ai_provider_primary = ""


class _ConfiguredSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "text-embedding-test"


@pytest.fixture
def no_embeddings(monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _NoModelSettings())


@pytest.fixture
def embeddings(monkeypatch):
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    seen: list[float] = []

    async def fake_embed(self, *, base_url, api_key, model, texts, _client=None, dimensions=None):
        value = 0.01 * (len(seen) + 1)
        seen.append(value)
        return [[value] * VECTOR_DIM for _ in texts]

    monkeypatch.setattr(EmbeddingProvider, "embed", fake_embed)
    return seen


async def _rows(db, tenant_id, key=None):
    stmt = select(KnowledgeItem).where(
        KnowledgeItem.tenant_id == tenant_id, KnowledgeItem.source_type == "policy"
    )
    if key:
        stmt = stmt.where(KnowledgeItem.source_ref == key)
    return (await db.execute(stmt)).scalars().all()


async def test_a_new_store_lists_all_four_policies_unwritten(db, tenant_ctx, no_embeddings):
    listed = await policies.list_policies(db, tenant_ctx.tenant_id)

    assert [p["key"] for p in listed] == ["exchange", "return", "shipping", "hours"]
    assert all(p["published"] is False and p["content"] == "" for p in listed)
    assert [p["title"] for p in listed][:2] == ["سياسة الاستبدال", "سياسة الاسترجاع"]


async def test_saving_creates_one_customer_facing_row(db, tenant_ctx, no_embeddings):
    saved = await policies.save_policy(
        db, tenant_ctx.tenant_id, "exchange", "  الاستبدال خلال 14 يوم بشرط الفاتورة.  "
    )

    assert saved["published"] is True and saved["content"] == "الاستبدال خلال 14 يوم بشرط الفاتورة."
    (row,) = await _rows(db, tenant_ctx.tenant_id, "exchange")
    assert row.visibility == "customer_facing" and row.title == "سياسة الاستبدال"
    listed = {p["key"]: p for p in await policies.list_policies(db, tenant_ctx.tenant_id)}
    assert listed["exchange"]["published"] and not listed["return"]["published"]


async def test_saving_twice_edits_the_same_row_not_a_duplicate(db, tenant_ctx, no_embeddings):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "return", "الاسترجاع خلال 7 أيام")
    await policies.save_policy(db, tenant_id, "return", "الاسترجاع خلال 3 أيام")

    (row,) = await _rows(db, tenant_id, "return")
    assert row.content == "الاسترجاع خلال 3 أيام"


async def test_blank_text_removes_the_policy_so_it_reads_as_unpublished(
    db, tenant_ctx, no_embeddings
):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "shipping", "الشحن 3 أيام")

    gone = await policies.save_policy(db, tenant_id, "shipping", "   ")

    assert gone["published"] is False and await _rows(db, tenant_id, "shipping") == []
    # removing something that was never written is harmless
    assert (await policies.save_policy(db, tenant_id, "hours", ""))["published"] is False


async def test_an_unknown_key_and_an_oversized_text_are_refused(db, tenant_ctx, no_embeddings):
    with pytest.raises(ValidationError, match="unknown policy"):
        await policies.save_policy(db, tenant_ctx.tenant_id, "warranty", "x")
    with pytest.raises(ValidationError, match="limit is"):
        await policies.save_policy(
            db, tenant_ctx.tenant_id, "return", "x" * (policies.MAX_POLICY_CHARS + 1)
        )
    assert await _rows(db, tenant_ctx.tenant_id) == []


async def test_without_an_embedding_model_it_is_saved_unindexed_and_still_readable(
    db, tenant_ctx, no_embeddings
):
    await policies.save_policy(db, tenant_ctx.tenant_id, "exchange", "الاستبدال خلال 14 يوم")

    (row,) = await _rows(db, tenant_ctx.tenant_id, "exchange")
    assert row.status == "pending" and row.embedding is None


async def test_editing_replaces_the_vector_so_search_never_answers_from_old_words(
    db, tenant_ctx, embeddings
):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "exchange", "النص القديم")
    (first,) = await _rows(db, tenant_id, "exchange")
    old_vector = list(first.embedding)

    await policies.save_policy(db, tenant_id, "exchange", "النص الجديد")

    (row,) = await _rows(db, tenant_id, "exchange")
    assert row.status == "indexed" and list(row.embedding) != old_vector


async def test_if_the_model_disappears_an_edit_does_not_keep_the_old_vector(
    db, tenant_ctx, embeddings, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "exchange", "النص القديم")
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _NoModelSettings())

    await policies.save_policy(db, tenant_id, "exchange", "النص الجديد")

    (row,) = await _rows(db, tenant_id, "exchange")
    assert row.embedding is None and row.status == "pending" and row.content == "النص الجديد"


async def test_the_customer_agent_reads_exactly_what_the_merchant_wrote(
    db, tenant_ctx, no_embeddings
):
    tenant_id = tenant_ctx.tenant_id
    spec = get_tool("get_store_info")
    assert "note" in await spec.handler(db, tenant_id)  # nothing written yet

    await policies.save_policy(db, tenant_id, "exchange", "الاستبدال خلال 14 يوم بشرط الفاتورة.")
    info = await spec.handler(db, tenant_id)

    assert [(i["title"], i["content"]) for i in info["items"]] == [
        ("سياسة الاستبدال", "الاستبدال خلال 14 يوم بشرط الفاتورة.")
    ]
    assert "note" not in info

    await policies.save_policy(db, tenant_id, "exchange", "")
    assert (await spec.handler(db, tenant_id))["items"] == []


async def test_one_stores_policies_are_invisible_to_another(db, tenant_ctx, no_embeddings):
    from app.core.db import bind_tenant

    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "exchange", "سياسة المتجر الأول")
    import uuid

    other = uuid.uuid4()
    await db.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
        {"id": str(other), "slug": f"other-{uuid.uuid4().hex[:8]}"},
    )
    await bind_tenant(db, other)

    listed = await policies.list_policies(db, other)
    assert not any(p["published"] for p in listed)
    # writing as the other store does not touch (or create) the first store's row
    await policies.save_policy(db, other, "exchange", "سياسة المتجر التاني")
    await bind_tenant(db, tenant_id)
    assert (await policies.list_policies(db, tenant_id))[0]["content"] == "سياسة المتجر الأول"
    count = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(KnowledgeItem.source_type == "policy")
        )
    ).scalar_one()
    assert count == 1  # row-level security: this session still sees only its own store


def test_the_routes_are_gated_by_settings_permissions() -> None:
    """Reading needs settings:read, writing needs settings:write. Nobody else, so a staff
    member without settings access cannot rewrite what the agent tells customers."""
    from app.modules.ai.routers.knowledge import router

    def codes(path: str, method: str) -> set[str]:
        (route,) = [r for r in router.routes if r.path == path and method in r.methods]
        return {d.call.code for d in route.dependant.dependencies if hasattr(d.call, "code")}

    assert codes("/ai/store-policies", "GET") == {"settings:read"}
    assert codes("/ai/store-policies/{key}", "PUT") == {"settings:write"}
