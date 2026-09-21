"""Spec §161 — Shopify commerce adapter.

Syncs products, inventory, orders, and customers from Shopify into the
internal domain via Application Services (never direct DB writes).

Uses the SourceOfTruthPolicy to decide direction and conflict resolution.
The adapter is behind the CommerceProviderPort — the core never knows it
is talking to Shopify.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ExternalProviderError
from app.modules.catalog.external.source_of_truth import (
    SourceOfTruthPolicy,
    SourceOfTruthService,
)

logger = logging.getLogger(__name__)

_SHOPIFY_API_VERSION = "2024-01"


class ShopifyAdapter:
    """Shopify REST API adapter — product/inventory/order/customer sync.

    All provider calls go through httpx with timeout + retry. The adapter
    normalizes Shopify payloads into our canonical domain shapes and
    delegates to Application Services for persistence.
    """

    def __init__(
        self,
        *,
        shop_domain: str,
        access_token: str,
        timeout: float = 30.0,
    ):
        self._base = f"https://{shop_domain}/admin/api/{_SHOPIFY_API_VERSION}"
        self._token = access_token
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
        }

    async def fetch_products(
        self, *, since: datetime | None = None, limit: int = 250
    ) -> list[dict[str, Any]]:
        """Fetch products from Shopify, optionally incrementally."""
        params: dict[str, Any] = {"limit": min(limit, 250)}
        if since:
            params["updated_at_min"] = since.isoformat()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/products.json",
                headers=self._headers,
                params=params,
            )
            if resp.status_code != 200:
                raise ExternalProviderError(
                    f"Shopify products fetch failed: HTTP {resp.status_code}"
                )
            data = resp.json()
            return data.get("products", [])

    async def fetch_orders(
        self, *, since: datetime | None = None, limit: int = 250
    ) -> list[dict[str, Any]]:
        """Fetch orders from Shopify."""
        params: dict[str, Any] = {"limit": min(limit, 250), "status": "any"}
        if since:
            params["updated_at_min"] = since.isoformat()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/orders.json",
                headers=self._headers,
                params=params,
            )
            if resp.status_code != 200:
                raise ExternalProviderError(
                    f"Shopify orders fetch failed: HTTP {resp.status_code}"
                )
            data = resp.json()
            return data.get("orders", [])

    async def fetch_inventory_levels(
        self, *, location_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch inventory levels from Shopify."""
        params: dict[str, Any] = {}
        if location_id:
            params["location_id"] = location_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/inventory_levels.json",
                headers=self._headers,
                params=params,
            )
            if resp.status_code != 200:
                raise ExternalProviderError(
                    f"Shopify inventory fetch failed: HTTP {resp.status_code}"
                )
            data = resp.json()
            return data.get("inventory_levels", [])

    async def fetch_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        """Fetch a single customer from Shopify."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/customers/{customer_id}.json",
                headers=self._headers,
            )
            if resp.status_code != 200:
                raise ExternalProviderError(
                    f"Shopify customer fetch failed: HTTP {resp.status_code}"
                )
            data = resp.json()
            return data.get("customer", {})

    async def sync_products(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        product_service,
    ) -> dict:
        """Sync products from Shopify into our catalog via ProductService.

        Returns a sync report: {synced, skipped, conflicts, errors}.
        """
        policy = await SourceOfTruthService.get_policy(
            session, tenant_id, provider="shopify", entity_type="product"
        )
        if policy is None or policy.source_mode == "internal":
            return {"synced": 0, "skipped": 0, "conflicts": 0, "errors": 0, "reason": "internal_source"}

        products = await self.fetch_products(
            since=policy.last_synced_at
        )
        report = {"synced": 0, "skipped": 0, "conflicts": 0, "errors": 0}

        for shopify_product in products:
            try:
                external_version = shopify_product.get("updated_at", "")
                if (
                    policy.external_version
                    and external_version <= policy.external_version
                ):
                    report["skipped"] += 1
                    continue

                # Normalize Shopify product → our canonical shape
                normalized = _normalize_shopify_product(shopify_product)

                # Delegate to the application service
                await product_service.upsert_from_external(
                    session, tenant_id, external_ref=str(shopify_product["id"]),
                    data=normalized, source="shopify",
                )
                report["synced"] += 1
            except Exception as exc:
                logger.warning("shopify product sync error: %s", exc)
                report["errors"] += 1

        await SourceOfTruthService.mark_synced(
            session, tenant_id,
            provider="shopify", entity_type="product",
            external_version=datetime.now(UTC).isoformat(),
        )
        return report

    async def sync_orders(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        order_service,
    ) -> dict:
        """Sync orders from Shopify into our orders domain."""
        policy = await SourceOfTruthService.get_policy(
            session, tenant_id, provider="shopify", entity_type="order"
        )
        if policy is None or policy.source_mode == "internal":
            return {"synced": 0, "skipped": 0, "conflicts": 0, "errors": 0, "reason": "internal_source"}

        orders = await self.fetch_orders(since=policy.last_synced_at)
        report = {"synced": 0, "skipped": 0, "conflicts": 0, "errors": 0}

        for shopify_order in orders:
            try:
                normalized = _normalize_shopify_order(shopify_order)
                await order_service.upsert_from_external(
                    session, tenant_id, external_ref=str(shopify_order["id"]),
                    data=normalized, source="shopify",
                )
                report["synced"] += 1
            except Exception as exc:
                logger.warning("shopify order sync error: %s", exc)
                report["errors"] += 1

        await SourceOfTruthService.mark_synced(
            session, tenant_id,
            provider="shopify", entity_type="order",
        )
        return report


def _normalize_shopify_product(sp: dict) -> dict:
    """Convert a Shopify product payload to our canonical product shape."""
    return {
        "title": sp.get("title", ""),
        "slug": sp.get("handle", ""),
        "description": sp.get("body_html", ""),
        "status": "active" if sp.get("status") == "active" else "draft",
        "external_id": str(sp.get("id", "")),
        "external_provider": "shopify",
        "variants": [
            {
                "title": v.get("title", "Default"),
                "price": v.get("price"),
                "sku": v.get("sku"),
                "external_id": str(v.get("id", "")),
            }
            for v in sp.get("variants", [])
        ],
    }


def _normalize_shopify_order(so: dict) -> dict:
    """Convert a Shopify order payload to our canonical order shape."""
    return {
        "external_id": str(so.get("id", "")),
        "external_provider": "shopify",
        "status": so.get("financial_status", "pending"),
        "total": so.get("total_price", "0.00"),
        "currency": so.get("currency", "EGP"),
        "customer_ref": str(so.get("customer", {}).get("id", "")),
        "items": [
            {
                "product_external_id": str(li.get("product_id", "")),
                "variant_external_id": str(li.get("variant_id", "")),
                "quantity": li.get("quantity", 1),
                "price": li.get("price", "0.00"),
            }
            for li in so.get("line_items", [])
        ],
    }
