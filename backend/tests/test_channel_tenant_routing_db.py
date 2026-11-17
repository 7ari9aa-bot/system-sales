"""resolve_channel_tenant must route EVERY connectable channel, on a real DB.

`scripts/provision.py` re-creates this function after every `alembic upgrade
head`. A stale copy there silently removed Facebook from routing (every Page
message was acknowledged and dropped), and the text-only test compared it with
an OLD migration so it could not notice. CI runs `alembic upgrade head` then
`scripts/provision.py` before pytest, so this asks the function exactly as that
leaves it: a channel missing from it (or from provision's copy) fails here.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.modules.platform.channel_specs import CONNECTION_SPECS
from app.modules.platform.models import Integration

# provider -> the config key the resolver matches on
_KEY = {
    "whatsapp": "phone_number_id",
    "messenger": "account_id",
    "instagram": "account_id",
    "facebook": "account_id",
    "webchat": "public_key",
}


async def _resolve(db, provider: str, key: str):
    row = await db.execute(
        sa.text("SELECT public.resolve_channel_tenant(:p, :k)"), {"p": provider, "k": key}
    )
    return row.scalar_one()


async def _connect(db, tenant_id, provider: str, config: dict) -> None:
    db.add(
        Integration(
            tenant_id=tenant_id, provider=provider, kind="channel", status="active", config=config
        )
    )
    await db.flush()


@pytest.mark.parametrize("provider", sorted(_KEY))
async def test_every_channel_routes_after_provision(db, tenant_ctx, provider: str) -> None:
    key = f"{provider}-{uuid.uuid4().hex[:8]}"
    await _connect(db, tenant_ctx.tenant.id, provider, {_KEY[provider]: key})

    assert await _resolve(db, provider, key) == tenant_ctx.tenant.id


async def test_telegram_routes_by_its_public_key(db, tenant_ctx) -> None:
    key = f"tg-{uuid.uuid4().hex[:8]}"
    await _connect(db, tenant_ctx.tenant.id, "telegram", {"public_key": key, "bot_id": "42"})

    assert await _resolve(db, "telegram", key) == tenant_ctx.tenant.id


async def test_a_legacy_facebook_page_id_still_routes(db, tenant_ctx) -> None:
    key = f"legacy-{uuid.uuid4().hex[:8]}"
    await _connect(db, tenant_ctx.tenant.id, "facebook", {"page_id": key})

    assert await _resolve(db, "facebook", key) == tenant_ctx.tenant.id


async def test_a_page_id_is_never_routed_under_another_provider(db, tenant_ctx) -> None:
    key = f"page-{uuid.uuid4().hex[:8]}"
    await _connect(db, tenant_ctx.tenant.id, "facebook", {"account_id": key})

    assert await _resolve(db, "messenger", key) is None
    assert await _resolve(db, "instagram", key) is None


def test_the_unique_index_covers_every_provider_that_the_resolver_routes() -> None:
    """A provider the resolver routes but the index omits can be double-connected."""
    index = next(
        i
        for i in Integration.__table__.indexes
        if i.name == "uq_integrations_active_channel_identity"
    )
    expression = str(index.expressions[1])
    for provider in _KEY:
        assert f"'{provider}'" in expression, provider
    assert "'telegram'" in expression


def test_this_file_covers_every_connectable_channel() -> None:
    """A newly added channel must be added to the routing function AND here."""
    covered = set(_KEY) | {"telegram"}
    assert set(CONNECTION_SPECS) == covered, (
        "a channel was added or removed: update resolve_channel_tenant "
        "(migration AND scripts/provision.py), the unique identity index, and this test"
    )
