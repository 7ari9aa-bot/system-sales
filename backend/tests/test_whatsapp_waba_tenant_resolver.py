"""`resolve_whatsapp_waba_tenant`: which store owns the business account a Meta event names.

Meta's template-status webhook carries the business account id and no phone number, so the
phone-number resolver cannot place it. The new function must place it for exactly one store, and
answer nothing in every doubtful case: filing an event under the wrong store would change another
merchant's template.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import encrypt_credentials_dict
from app.modules.identity.models import Tenant
from app.modules.platform.models import Integration

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = BACKEND / "migrations" / "versions" / "fe2026112002_resolve_whatsapp_waba_tenant.py"
PROVISION = BACKEND / "scripts" / "provision.py"


def _assigned_string(path: Path, name: str) -> str:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path.name}")


def _effective(sql: str) -> str:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return " ".join(" ".join(lines).split())


# ---- static: no database needed ------------------------------------------------------------


def test_migration_and_provision_define_the_same_function() -> None:
    """They run in either order; a divergence would make the function depend on which ran last."""
    assert _effective(_assigned_string(MIGRATION, "_WABA_TENANT_FN")) == _effective(
        _assigned_string(PROVISION, "WABA_TENANT_FN_SQL")
    )


def test_the_function_parses_and_is_locked_down() -> None:
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    sql = _assigned_string(MIGRATION, "_WABA_TENANT_FN")
    pglast.parser.parse_sql(sql)
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = public, pg_temp" in sql  # mandatory for SECURITY DEFINER
    assert "RETURNS uuid" in sql  # the store id only, never the credentials in `config`
    source = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL ON FUNCTION public.resolve_whatsapp_waba_tenant(text) FROM PUBLIC" in source
    assert "GRANT EXECUTE ON FUNCTION public.resolve_whatsapp_waba_tenant(text)" in source


def test_provision_grants_and_revokes_the_new_function_too() -> None:
    """CI runs the migration and THEN provision.py, which must leave it callable by the app."""
    source = PROVISION.read_text(encoding="utf-8")
    assert (
        "GRANT EXECUTE ON FUNCTION public.resolve_whatsapp_waba_tenant(text) TO sales_app" in source
    )
    assert "WABA_TENANT_FN_REVOKE" in source


# ---- real database (runs in CI; skipped where no app database is configured) ----------------


async def _channel(
    db: AsyncSession, tenant_id, *, waba, status="active", provider="whatsapp", kind="channel"
) -> None:
    db.add(
        Integration(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            kind=kind,
            status=status,
            config={"waba_id": waba, "phone_number_id": uuid.uuid4().hex[:12]},
            credentials=encrypt_credentials_dict({"access_token": "secret"}),
        )
    )
    await db.flush()


async def _resolve(db: AsyncSession, waba):
    row = await db.execute(sa_text("SELECT public.resolve_whatsapp_waba_tenant(:w)"), {"w": waba})
    return row.scalar()


async def _other_tenant(db: AsyncSession) -> uuid.UUID:
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Test Tenant")
    db.add(tenant)
    await db.flush()
    return tenant.id


async def test_finds_the_one_store_that_owns_the_account(db: AsyncSession, tenant_ctx) -> None:
    waba = uuid.uuid4().hex[:15]
    await _channel(db, tenant_ctx.tenant_id, waba=waba)
    assert str(await _resolve(db, waba)) == str(tenant_ctx.tenant_id)


async def test_a_connected_channel_counts_like_an_active_one(db: AsyncSession, tenant_ctx) -> None:
    waba = uuid.uuid4().hex[:15]
    await _channel(db, tenant_ctx.tenant_id, waba=waba, status="connected")
    assert str(await _resolve(db, waba)) == str(tenant_ctx.tenant_id)


@pytest.mark.parametrize("status", ["paused", "reauth_required", "disabled"])
async def test_a_channel_that_is_not_live_receives_nothing(
    db: AsyncSession, tenant_ctx, status: str
) -> None:
    waba = uuid.uuid4().hex[:15]
    await _channel(db, tenant_ctx.tenant_id, waba=waba, status=status)
    assert await _resolve(db, waba) is None


async def test_two_stores_claiming_one_account_get_nothing(db: AsyncSession, tenant_ctx) -> None:
    """Guessing would file one merchant's template change under another."""
    from app.core.db import bind_tenant

    waba = uuid.uuid4().hex[:15]
    other = await _other_tenant(db)
    # integrations is row-level-secured to the bound store, so each store's row is written while
    # THAT store is bound; the resolver is SECURITY DEFINER and must still see both.
    await bind_tenant(db, tenant_ctx.tenant_id)
    await _channel(db, tenant_ctx.tenant_id, waba=waba)
    await bind_tenant(db, other)
    await _channel(db, other, waba=waba)
    await bind_tenant(db, tenant_ctx.tenant_id)
    # Both stores really hold the account (else None below would mean "unknown", not "ambiguous").
    assert (
        await db.execute(
            sa_text("SELECT count(*) FROM integrations WHERE config->>'waba_id' = :w"), {"w": waba}
        )
    ).scalar() >= 1
    assert await _resolve(db, waba) is None


async def test_relinking_to_another_account_moves_the_match(db: AsyncSession, tenant_ctx) -> None:
    """A store holds one WhatsApp channel; re-linking it to a new account must stop the old id."""
    old, new = uuid.uuid4().hex[:15], uuid.uuid4().hex[:15]
    await _channel(db, tenant_ctx.tenant_id, waba=old)
    row = (
        await db.execute(select(Integration).where(Integration.tenant_id == tenant_ctx.tenant_id))
    ).scalar_one()
    row.config = {**row.config, "waba_id": new}
    await db.flush()
    assert await _resolve(db, old) is None
    assert str(await _resolve(db, new)) == str(tenant_ctx.tenant_id)


async def test_other_providers_and_kinds_are_ignored(db: AsyncSession, tenant_ctx) -> None:
    waba = uuid.uuid4().hex[:15]
    await _channel(db, tenant_ctx.tenant_id, waba=waba, provider="telegram")
    await _channel(db, tenant_ctx.tenant_id, waba=waba, kind="ai")
    assert await _resolve(db, waba) is None


@pytest.mark.parametrize("key", [None, "", "no-such-account"])
async def test_an_empty_or_unknown_key_matches_nothing(db: AsyncSession, tenant_ctx, key) -> None:
    """A channel linked without an account id stores '' — an empty key must never match it."""
    await _channel(db, tenant_ctx.tenant_id, waba="")
    assert await _resolve(db, key) is None
