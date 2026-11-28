"""Two taps on 'I sell clothes' at the same moment plant one tree, not two.

Real concurrency on committed connections: the per-test `db` fixture is one rolled-back
connection and cannot show a race. This commits a throw-away tenant, races real connections, and
deletes everything it created.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.security import hash_password
from app.core.shop_type import APPAREL_STARTER_TREE, choose_vertical
from app.platform.identity.models import Role, Tenant, TenantUser, User

RACERS = 8
EXPECTED = len(APPAREL_STARTER_TREE) + sum(len(v) for v in APPAREL_STARTER_TREE.values())


@pytest.fixture
async def committed_tenant(db_url):
    engine = create_async_engine(
        db_url, pool_size=RACERS + 2, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"v-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name="V",
        )
        tenant = Tenant(id=tenant_id, slug=f"v-{uuid.uuid4().hex[:8]}", name="VerticalRace")
        s.add_all([tenant, user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    try:
        yield factory, tenant_id, user_id
    finally:
        async with factory() as s:
            await s.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            for table in ("categories", "tenant_settings_history", "tenant_settings"):
                await s.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await s.commit()
        async with factory() as s:
            await s.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            await s.execute(
                sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)}
            )
            await s.execute(
                sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await s.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            deleted = await s.execute(
                sa.text("DELETE FROM tenants WHERE id = :t RETURNING id"), {"t": tenant_id}
            )
            assert deleted.first() is not None, (
                "cleanup failed: the throw-away tenant is still there"
            )
            await s.commit()
        await engine.dispose()


async def _choose(factory, tenant_id, user_id):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            out = await choose_vertical(s, tenant_id, "apparel", user_id=user_id)
            await s.commit()
            return out["categories_created"]
        except Exception as exc:  # noqa: BLE001 - the test reports whatever a racer hit
            await s.rollback()
            return exc


@pytest.mark.asyncio
async def test_racing_choices_plant_exactly_one_tree(committed_tenant) -> None:
    factory, tenant_id, user_id = committed_tenant
    results = await asyncio.gather(*(_choose(factory, tenant_id, user_id) for _ in range(RACERS)))
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    assert sorted(results, reverse=True)[0] == EXPECTED
    assert sum(results) == EXPECTED, (
        f"planted {sum(results)} categories, expected one tree of {EXPECTED}"
    )
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        total = (
            await s.execute(
                sa.text("SELECT count(*) FROM categories WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    assert total == EXPECTED
