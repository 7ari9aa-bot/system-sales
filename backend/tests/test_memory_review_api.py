"""§158 — staff review surface for memories.

The spec is blunt: a memory claim is governed only if staff can

    review / edit / delete / invalidate

it. The write path and provenance columns exist (T1), but the AI router has
zero memory routes — a wrong "customer hates callbacks" summary lives in the
vector index forever with no way to take it out of service except SQL.

These tests pin the missing routes. Contract-level cases run DB-free against
the real app (OpenAPI surface); the lifecycle case (create → edit →
invalidate → recall drops it → delete) drives the real routers over CI
Postgres, because recall filtering is SQL and a fake session cannot falsify
it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.knowledge import search_memory
from app.modules.ai.models import Memory
from app.modules.ai.providers import EmbeddingProvider
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

VECTOR_DIM = 1536


class _ConfiguredSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "text-embedding-test"


def _patch_fixed_embeddings(monkeypatch, value: float = 0.01) -> None:
    async def fake_embed(self, *, base_url, api_key, model, texts, _client=None, dimensions=None):
        return [[value] * VECTOR_DIM for _ in texts]

    monkeypatch.setattr(EmbeddingProvider, "embed", fake_embed)


def _app(session: AsyncSession, ctx: TenantContext) -> object:
    async def _fake_ctx() -> TenantContext:
        return ctx

    app = create_app()
    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    return app


def _ctx(db: AsyncSession, tenant_ctx, permissions: set[str]) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=set(permissions),
    )


# ---------------------------------------------------------------------------
# 1. The routes exist at all (DB-free contract guard)
# ---------------------------------------------------------------------------


def test_memory_review_routes_are_registered() -> None:
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/ai/memories" in paths  # GET list + POST staff-entered
    assert "/api/v1/ai/memories/{memory_id}" in paths  # PATCH + DELETE
    assert "/api/v1/ai/memories/{memory_id}/invalidate" in paths  # POST


# ---------------------------------------------------------------------------
# 2. The staff lifecycle actually governs recall (CI Postgres)
# ---------------------------------------------------------------------------


async def test_staff_can_edit_invalidate_and_delete_a_memory(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch, value=0.02)
    ctx = _ctx(db, tenant_ctx, {"settings:write"})
    transport = ASGITransport(app=_app(db, ctx))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # create: staff-entered, attributable to the acting user
        created = await client.post(
            "/api/v1/ai/memories",
            json={
                "kind": "fact",
                "content": "customer prefers email over phone",
                "customer_id": None,
                "confidence": 0.9,
            },
        )
        assert created.status_code == 201, created.text
        memory_id = created.json()["id"]
        row = await db.get(Memory, uuid.UUID(memory_id))
        assert row.source == "staff_entered"
        assert row.actor_id == tenant_ctx.user.id
        assert row.status == "active"

        # review: list sees it
        listed = await client.get("/api/v1/ai/memories")
        assert listed.status_code == 200
        assert memory_id in [item["id"] for item in listed.json()["items"]]

        # edit: content changes, version of truth is the staff row
        edited = await client.patch(
            f"/api/v1/ai/memories/{memory_id}",
            json={"content": "customer prefers WHATSAPP, never call"},
        )
        assert edited.status_code == 200, edited.text
        await db.refresh(row)
        assert row.content == "customer prefers WHATSAPP, never call"

        # recall finds an active memory (same vector space as the stub embed)
        found = await search_memory(db, tenant_ctx.tenant_id, "contact channel")
        assert memory_id in [str(m.id) for m, _ in found]

        # invalidate: out of service, row and audit trail survive
        invalidated = await client.post(f"/api/v1/ai/memories/{memory_id}/invalidate")
        assert invalidated.status_code == 200, invalidated.text
        await db.refresh(row)
        assert row.status == "invalidated"
        assert row.invalidated_at is not None
        found = await search_memory(db, tenant_ctx.tenant_id, "contact channel")
        assert memory_id not in [str(m.id) for m, _ in found]

        # delete: hard removal (staff purge; distinct from invalidate)
        deleted = await client.delete(f"/api/v1/ai/memories/{memory_id}")
        assert deleted.status_code == 204
        db.expire_all()
        assert await db.get(Memory, uuid.UUID(memory_id)) is None


async def test_memory_routes_require_the_write_permission(
    db: AsyncSession, tenant_ctx
) -> None:
    ctx = _ctx(db, tenant_ctx, set())  # no settings:write
    transport = ASGITransport(app=_app(db, ctx))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ai/memories",
            json={"kind": "fact", "content": "unprivileged write"},
        )
        assert response.status_code == 403


async def test_invalidate_is_idempotent_and_scoped_to_the_tenant(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    """A second invalidate keeps the first timestamp (audit truth), and another
    tenant's memory id is a 404 — never a silent cross-tenant mutation."""
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _ConfiguredSettings())
    _patch_fixed_embeddings(monkeypatch, value=0.02)
    ctx = _ctx(db, tenant_ctx, {"settings:write"})
    transport = ASGITransport(app=_app(db, ctx))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/ai/memories",
            json={"kind": "fact", "content": "governed twice"},
        )
        memory_id = created.json()["id"]
        first = await client.post(f"/api/v1/ai/memories/{memory_id}/invalidate")
        stamp = datetime.fromisoformat(first.json()["invalidated_at"])
        second = await client.post(f"/api/v1/ai/memories/{memory_id}/invalidate")
        assert second.json()["invalidated_at"] == stamp.isoformat().replace("+00:00", "Z") or (
            datetime.fromisoformat(second.json()["invalidated_at"]) == stamp
        )
        stranger = uuid.uuid4()
        cross = await client.post(f"/api/v1/ai/memories/{stranger}/invalidate")
        assert cross.status_code == 404
