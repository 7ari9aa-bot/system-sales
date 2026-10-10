"""Vision tool tests (spec §11/§12.5/§13) — gating, server-bound image, ids only.

find_product_by_image: the classifier DECIDES what the proposed kind may do —
only PRODUCT runs the pipeline, payment proofs and complaints hand over with
the reason named, and the photo itself comes from the runner-injected
context, never from model arguments. resolve_product_media: gallery image
ids only — a URL must never cross the model boundary.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import DomainError, NotFoundError
from app.modules.ai.agents.customer.vision import pipeline
from app.modules.ai.agents.customer.vision.schemas import MatchResult
from app.modules.ai.tools import _find_product_by_image, _resolve_product_media, get_tool
from app.modules.catalog.models import Product, ProductImage


async def test_registry_exposes_both_vision_tools_as_low_risk():
    for name in ("find_product_by_image", "resolve_product_media"):
        spec = get_tool(name)
        assert spec is not None, name
        assert spec.risk_level == "LOW"


async def test_payment_proof_refused_with_handover_reason(db, tenant_ctx):
    with pytest.raises(DomainError, match="payment_proof_requires_human"):
        await _find_product_by_image(
            db,
            tenant_ctx.tenant_id,
            image_kind="payment_proof",
            context={"customer_image": "https://c.test/receipt.png"},
        )


async def test_complaint_refused_with_handover_reason(db, tenant_ctx):
    with pytest.raises(DomainError, match="complaint_requires_human"):
        await _find_product_by_image(db, tenant_ctx.tenant_id, image_kind="complaint", context={})


async def test_non_product_kind_refused(db, tenant_ctx):
    with pytest.raises(DomainError, match="not_a_product_image"):
        await _find_product_by_image(db, tenant_ctx.tenant_id, image_kind="size_chart", context={})


async def test_product_kind_without_bound_image_refused(db, tenant_ctx):
    # The photo is SERVER-BOUND: no runner-injected context, no pipeline —
    # the model can never supply (or invent) the image itself.
    with pytest.raises(DomainError, match="no customer image"):
        await _find_product_by_image(db, tenant_ctx.tenant_id, image_kind="product", context=None)


async def test_product_match_result_is_business_only(monkeypatch, db, tenant_ctx):
    async def fake_match(session, tenant_id, *, image_url, text_hint=None):
        assert image_url == "https://storage.test/signed/customer.png"
        assert text_hint == "abaya كحلي"
        return MatchResult(
            confidence=__import__(
                "app.modules.ai.agents.customer.vision.schemas", fromlist=["Confidence"]
            ).Confidence.HIGH,
            candidates=[
                {
                    "product_id": str(uuid.uuid4()),
                    "title": "Blue Abaya",
                    "verified": True,
                    "available_variants": 3,
                }
            ],
            reason="clear_match",
            as_of="2026-09-30T00:00:00+00:00",
        )

    monkeypatch.setattr(pipeline, "run_vision_match", fake_match)
    result = await _find_product_by_image(
        db,
        tenant_ctx.tenant_id,
        image_kind="product",
        hints="abaya كحلي",
        context={"customer_image": "https://storage.test/signed/customer.png"},
    )
    assert result["confidence"] == "high"
    assert result["reason"] == "clear_match"
    dumped = repr(result)
    # §12.3: no URLs, no scores anywhere in the model-visible payload.
    assert "http" not in dumped and "score" not in dumped and "distance" not in dumped


async def test_resolve_product_media_primary_returns_one_id(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = Product(
        tenant_id=tenant_id,
        title="Abaya",
        slug=f"abaya-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    for position in (2, 0, 1):
        db.add(
            ProductImage(
                tenant_id=tenant_id,
                product_id=product.id,
                url=f"https://cdn.test/{position}.png",
                position=position,
            )
        )
    await db.flush()

    result = await _resolve_product_media(db, tenant_id, product_id=product.id, selection="primary")
    assert len(result["media"]) == 1
    only = result["media"][0]
    assert set(only) == {"image_id", "alt", "position"}
    assert only["position"] == 0  # lowest position wins, whatever the insert order
    # §13: ids never URLs.
    assert "url" not in repr(result).lower()


async def test_resolve_product_media_all_orders_by_position(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    product = Product(
        tenant_id=tenant_id,
        title="Abaya",
        slug=f"abaya-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    for position in (2, 0, 1):
        db.add(
            ProductImage(
                tenant_id=tenant_id,
                product_id=product.id,
                url=f"https://cdn.test/{position}.png",
                position=position,
            )
        )
    await db.flush()

    result = await _resolve_product_media(db, tenant_id, product_id=product.id, selection="all")
    assert [m["position"] for m in result["media"]] == [0, 1, 2]
    assert all(set(m) == {"image_id", "alt", "position"} for m in result["media"])


async def test_resolve_product_media_unknown_product_fails_loudly(db, tenant_ctx):
    """Unknown metric, unknown product — a tool that invents an empty success
    for a nonexistent entity lets the model answer from nothing."""
    with pytest.raises(NotFoundError, match="not found"):
        await _resolve_product_media(
            db, tenant_ctx.tenant_id, product_id=uuid.uuid4(), selection="all"
        )
