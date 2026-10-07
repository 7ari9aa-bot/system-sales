"""§179 identifiers — DB-backed behaviour (Commerce Core v1.0 Phase P1).

Runs wherever a database URL is configured (CI and this workspace's local
Postgres); ``conftest`` skips with a clear message otherwise. The DB-free
contract guards live in ``test_catalog_identifiers_spec.py``.

Discipline note (AGENT_BRIEF §3a): assertions bind scalars immediately —
``resolved.id == variant.id`` compares two already-loaded UUIDs, and every
read goes through an explicit ``SELECT`` that returns plain values, so no
lazy refresh can ever occur.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError


async def _variant_with_ean(db, tenant_ctx, value: str = "1234567890123"):
    product = await CatalogService.create_product(
        db,
        tenant_ctx.tenant_id,
        title="تيشيرت",
        slug=f"tshirt-{uuid.uuid4().hex[:10]}",
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="أسود / L", price="150.00"
    )
    await CatalogService.add_identifier(db, tenant_ctx.tenant_id, variant.id, "ean", value)
    return variant


async def test_add_then_resolve_roundtrip(db, tenant_ctx):
    variant = await _variant_with_ean(db, tenant_ctx)
    resolved = await CatalogService.resolve_identifier(
        db, tenant_ctx.tenant_id, "ean", "1234567890123"
    )
    assert resolved is not None
    assert resolved.id == variant.id


async def test_resolve_is_none_for_unknown_value(db, tenant_ctx):
    resolved = await CatalogService.resolve_identifier(
        db, tenant_ctx.tenant_id, "ean", "0000000000000"
    )
    assert resolved is None


async def test_duplicate_identifier_conflicts_after_value_normalization(db, tenant_ctx):
    variant = await _variant_with_ean(db, tenant_ctx, "2222222222222")
    with pytest.raises(ConflictError):
        await CatalogService.add_identifier(
            db, tenant_ctx.tenant_id, variant.id, "ean", "  2222222222222  "
        )


async def test_same_value_across_types_is_two_rows(db, tenant_ctx):
    variant = await _variant_with_ean(db, tenant_ctx, "3333333333333")
    await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "barcode", "3333333333333"
    )
    rows = await CatalogService.list_identifiers(db, tenant_ctx.tenant_id, variant.id)
    assert {r.type for r in rows} == {"ean", "barcode"}


async def test_cross_tenant_resolve_is_none(db, tenant_ctx):
    await _variant_with_ean(db, tenant_ctx, "4444444444444")
    resolved = await CatalogService.resolve_identifier(db, uuid.uuid4(), "ean", "4444444444444")
    assert resolved is None


async def test_unknown_type_is_refused_before_any_query(db, tenant_ctx):
    with pytest.raises(ValidationError):
        await CatalogService.resolve_identifier(db, tenant_ctx.tenant_id, "ean13", "5555555555555")
