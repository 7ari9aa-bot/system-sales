"""6.3 close-out — the durable vision indexing sweep.

The indexer itself was always fine (idempotent upsert, governed gateway,
model identity pinned) — what was missing was ANYTHING calling it: production
sat at product_images=1 / product_embeddings=0 behind a manual CLI. These
tests pin the operational half that closes that hole:

1. the sweep indexes images that lack an embedding for the CURRENT model;
2. a second sweep makes ZERO embedding calls (only-missing selection);
3. a lost embedding row is reconciled on the next sweep;
4. one tenant's provider failure does not block the other tenants, and the
   failed tenant is retried on the next sweep;
5. the sweep is a REGISTERED global sweeper — deleting the registration
   fails the deployment-declaration governance test by construction.

Seeding uses REAL committed rows (own engine, own tenant, cascade cleanup):
the sweep opens its own sessions, so savepoint-nested fixture data would be
invisible to it — the same isolation rule the fk-index guard tests follow.
Every test cascade-drops the tenants it created, because the sweep COMMITS —
a failed run must not shift the next test's counters.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.ai.agents.customer.vision.indexer import (
    sweep_unindexed_product_images,
)


def _app_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("DATABASE_URL not configured — the sweep opens its own sessions")
    return dsn


@pytest.fixture()
async def sessions():
    engine = create_async_engine(_app_dsn(), connect_args={"statement_cache_size": 0})
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _cleanup(maker, tenant_ids: list[uuid.UUID]) -> None:
    """Cascade-drop the tenants a test created (the sweep commits its work,
    so cleanup has to be explicit and unconditional).

    Runs as the ADMIN role on purpose: the tenants DELETE policy is
    GUC-scoped, so an unbound app-role session matches zero rows and the
    cleanup would silently no-op (RLS denies are invisible)."""
    if not tenant_ids:
        return
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url_admin)
    try:
        async with engine.begin() as conn:
            for tid in tenant_ids:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": str(tid)})
    finally:
        await engine.dispose()


async def _new_tenant(maker, tenants: list[uuid.UUID]) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    async with maker() as session:
        await session.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"),
            {
                "id": tenant_id,
                "slug": f"vis-{uuid.uuid4().hex[:10]}",
                "name": "Vision Sweep Tenant",
            },
        )
        await session.commit()
    tenants.append(tenant_id)
    return tenant_id


async def _seed_product_image(maker, tenant_id: uuid.UUID, title: str) -> uuid.UUID:
    """Active product + one image, committed as the app role with the tenant
    GUC bound (RLS admits the write; the sweep's own sessions must see it)."""
    async with maker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        product_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO products (id, tenant_id, title, slug, status) "
                "VALUES (:id, :t, :title, :slug, 'active')"
            ),
            {
                "id": product_id,
                "t": str(tenant_id),
                "title": title,
                "slug": f"{title.lower()}-{uuid.uuid4().hex[:8]}",
            },
        )
        image_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO product_images (id, tenant_id, product_id, url) "
                "VALUES (:id, :t, :p, :url)"
            ),
            {
                "id": image_id,
                "t": str(tenant_id),
                "p": str(product_id),
                "url": f"https://cdn.test/{uuid.uuid4().hex}.png",
            },
        )
        await session.commit()
    return image_id


async def _embedding_count(maker, tenant_id: uuid.UUID) -> int:
    async with maker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        row = (
            await session.execute(
                text("SELECT count(*) FROM product_embeddings WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
        ).scalar_one()
    return int(row)


class _ScriptedGateway:
    """Stands in for AIGateway.embed_vision: records tenant calls, returns
    one distinct vector per requested item, and can fail on demand."""

    def __init__(self):
        self.calls: list[uuid.UUID] = []
        self.fail_for: set[uuid.UUID] = set()

    async def embed_vision(self, session, tenant_id, *, contents, _client=None):
        self.calls.append(tenant_id)
        if tenant_id in self.fail_for:
            raise RuntimeError("vision provider down")
        return [[0.0] * 768 for _ in contents]


@pytest.fixture()
def sweep_sessions(monkeypatch, sessions):
    """Point the app's session factory at THIS test's loop-bound maker.

    The sweep opens its own sessions through ``app.core.db.SessionLocal`` —
    a lazy ``__getattr__`` product whose asyncpg pool is bound to whichever
    event loop created it, and pytest-asyncio hands every test a fresh loop.
    Patch ``get_sessionmaker`` (never assign SessionLocal itself: restoring
    by assignment would permanently shadow the lazy attribute) so the sweep's
    sessions ride this test's engine AND see its committed seed rows.
    """
    from app.core import db as db_mod

    monkeypatch.setattr(db_mod, "get_sessionmaker", lambda: sessions, raising=False)
    return sessions


@pytest.fixture()
def fake_gateway(monkeypatch):
    from app.modules.ai import gateway as gateway_mod

    fake = _ScriptedGateway()
    monkeypatch.setattr(gateway_mod.AIGateway, "embed_vision", fake.embed_vision)
    return fake


# ------------------------------------------------------------ the sweeps -----


async def test_sweep_indexes_images_missing_the_current_model(sweep_sessions, fake_gateway) -> None:
    tenants: list[uuid.UUID] = []
    try:
        tenant_id = await _new_tenant(sweep_sessions, tenants)
        await _seed_product_image(sweep_sessions, tenant_id, "Sweep Item")

        indexed = await sweep_unindexed_product_images()

        assert indexed == 1
        assert fake_gateway.calls == [tenant_id]
        assert await _embedding_count(sweep_sessions, tenant_id) == 1
    finally:
        await _cleanup(sweep_sessions, tenants)


async def test_second_sweep_makes_zero_embedding_calls(sweep_sessions, fake_gateway) -> None:
    tenants: list[uuid.UUID] = []
    try:
        tenant_id = await _new_tenant(sweep_sessions, tenants)
        await _seed_product_image(sweep_sessions, tenant_id, "Only Once")

        assert await sweep_unindexed_product_images() == 1
        calls_after_first = len(fake_gateway.calls)

        await sweep_unindexed_product_images()
        assert len(fake_gateway.calls) == calls_after_first, (
            "already-indexed images must not be re-embedded by the reconciliation sweep"
        )
        assert await _embedding_count(sweep_sessions, tenant_id) == 1
    finally:
        await _cleanup(sweep_sessions, tenants)


async def test_a_lost_embedding_row_is_reconciled(sweep_sessions, fake_gateway) -> None:
    tenants: list[uuid.UUID] = []
    try:
        tenant_id = await _new_tenant(sweep_sessions, tenants)
        image_id = await _seed_product_image(sweep_sessions, tenant_id, "Reconciled")
        assert await sweep_unindexed_product_images() == 1

        # Simulate the loss the reconciliation exists for (failed batch, model
        # change, manual purge): the row disappears, the sweep restores it.
        async with sweep_sessions() as session:
            # The DELETE is RLS-scoped like every write here: bind the tenant
            # GUC first or the deny matches zero rows silently.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(tenant_id)},
            )
            await session.execute(
                text("DELETE FROM product_embeddings WHERE product_image_id = :i"),
                {"i": str(image_id)},
            )
            await session.commit()
        assert await _embedding_count(sweep_sessions, tenant_id) == 0

        assert await sweep_unindexed_product_images() == 1
        assert await _embedding_count(sweep_sessions, tenant_id) == 1
    finally:
        await _cleanup(sweep_sessions, tenants)


async def test_one_tenant_failure_does_not_block_the_others(sweep_sessions, fake_gateway) -> None:
    tenants: list[uuid.UUID] = []
    try:
        tenant_a = await _new_tenant(sweep_sessions, tenants)
        tenant_b = await _new_tenant(sweep_sessions, tenants)
        await _seed_product_image(sweep_sessions, tenant_a, "Broken A")
        await _seed_product_image(sweep_sessions, tenant_b, "Healthy B")
        fake_gateway.fail_for = {tenant_a}

        assert await sweep_unindexed_product_images() == 1
        assert await _embedding_count(sweep_sessions, tenant_a) == 0
        assert await _embedding_count(sweep_sessions, tenant_b) == 1

        # The provider heals: the next sweep reconciles the failed tenant.
        fake_gateway.fail_for = set()
        assert await sweep_unindexed_product_images() == 1
        assert await _embedding_count(sweep_sessions, tenant_a) == 1
    finally:
        await _cleanup(sweep_sessions, tenants)


async def test_the_sweep_is_a_registered_global_sweeper() -> None:
    from app.workers import scheduler_worker

    assert "vision.product_indexing" in scheduler_worker.GLOBAL_SWEEPERS
