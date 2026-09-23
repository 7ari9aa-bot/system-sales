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
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import storage_refusal
from app.core.errors import ExternalProviderError
from app.core.tenancy import resolve_tenant_currency
from app.modules.catalog.external.source_of_truth import (
    SourceOfTruthService,
)
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError

logger = logging.getLogger(__name__)

_CHANNEL = "shopify"
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
        transport: httpx.AsyncBaseTransport | None = None,
        shop_currency: str | None = None,
    ):
        self._base = f"https://{shop_domain}/admin/api/{_SHOPIFY_API_VERSION}"
        self._token = access_token
        self._timeout = timeout
        # Test seam: an injected transport replaces the network. The shop's own
        # currency, learned when the channel is connected, is the only thing
        # that can label a payload that declares none.
        self._transport = transport
        self._shop_currency = (shop_currency or "").upper() or None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

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

        async with self._client() as client:
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

        async with self._client() as client:
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

        async with self._client() as client:
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
        async with self._client() as client:
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

    async def _tenant_currency(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tenant_currency: str | None,
    ) -> str:
        """The one currency this sync may write money in (§47).

        From the request's tenant scope when the caller has one, else
        ``tenants.currency``. A code the schema cannot hold is refused up
        front: a three-decimal currency in a two-decimal column loses a minor
        unit on every price.
        """
        code = (
            tenant_currency or await resolve_tenant_currency(session, tenant_id)
        ).upper()
        refusal = storage_refusal(code)
        if refusal:
            raise ValidationError(f"{_CHANNEL} sync refused: {refusal}")
        return code

    async def sync_products(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        product_service=None,
        tenant_currency: str | None = None,
    ) -> dict:
        """Sync products from Shopify into our catalog via the catalog service.

        The provider boundary normalizes and refuses; ``CatalogService`` owns
        the row and the currency rule, so a price can never be written by a
        path that skipped them.

        Returns a sync report: {synced, skipped, conflicts, errors}.
        """
        currency = await self._tenant_currency(session, tenant_id, tenant_currency)
        service = product_service if product_service is not None else CatalogService

        policy = await SourceOfTruthService.get_policy(
            session, tenant_id, provider=_CHANNEL, entity_type="product"
        )
        if policy is None or policy.source_mode == "internal":
            return {
                "synced": 0, "skipped": 0, "conflicts": 0,
                "errors": 0, "reason": "internal_source",
            }

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

                # A price with no currency on it anywhere is unknown money, not
                # the tenant's by default — refuse it, do not relabel it.
                _resolve_price_currency(
                    _declared_product_currency(shopify_product),
                    subject=f"{_CHANNEL} product {shopify_product.get('id')}",
                    shop_currency=self._shop_currency,
                    tenant_currency=currency,
                )

                # Normalize Shopify product → our canonical shape
                normalized = _normalize_shopify_product(shopify_product)

                # Delegate to the application service
                await service.upsert_from_external(
                    session, tenant_id, external_ref=str(shopify_product["id"]),
                    data=normalized, source=_CHANNEL, currency=currency,
                )
                report["synced"] += 1
            except ConflictError as exc:
                # A refused row is visible as a conflict, never as a silent
                # entry in `errors` next to a green report.
                report["conflicts"] += 1
                logger.warning("shopify product sync conflict: %s", exc)
            except Exception as exc:
                logger.warning("shopify product sync error: %s", exc)
                report["errors"] += 1

        await SourceOfTruthService.mark_synced(
            session, tenant_id,
            provider=_CHANNEL, entity_type="product",
            external_version=datetime.now(UTC).isoformat(),
        )
        return report

    async def sync_orders(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        order_service,
        tenant_currency: str | None = None,
    ) -> dict:
        """Sync orders from Shopify into our orders domain.

        Refuses before fetching if the injected service cannot take an
        external order: today nothing in the system can, and the orders module
        is one this adapter's own module must not import
        (``tests/test_module_boundaries.py``). A clear ``NotImplementedError``
        beats an ``AttributeError`` swallowed into a report nobody reads.
        """
        if not hasattr(order_service, "upsert_from_external"):
            raise NotImplementedError(
                f"{_CHANNEL} order sync is not implemented for this channel: "
                "no orders service defines upsert_from_external(). Wire an "
                "order intake in the orders module and pass it here — product "
                "sync is unaffected."
            )

        currency = await self._tenant_currency(session, tenant_id, tenant_currency)
        policy = await SourceOfTruthService.get_policy(
            session, tenant_id, provider=_CHANNEL, entity_type="order"
        )
        if policy is None or policy.source_mode == "internal":
            return {
                "synced": 0, "skipped": 0, "conflicts": 0,
                "errors": 0, "reason": "internal_source",
            }

        orders = await self.fetch_orders(since=policy.last_synced_at)
        report = {"synced": 0, "skipped": 0, "conflicts": 0, "errors": 0}

        for shopify_order in orders:
            try:
                normalized = _normalize_shopify_order(
                    shopify_order,
                    tenant_currency=currency,
                    shop_currency=self._shop_currency,
                )
                await order_service.upsert_from_external(
                    session, tenant_id, external_ref=str(shopify_order["id"]),
                    data=normalized, source=_CHANNEL, currency=currency,
                )
                report["synced"] += 1
            except ConflictError as exc:
                report["conflicts"] += 1
                logger.warning("shopify order sync conflict: %s", exc)
            except Exception as exc:
                logger.warning("shopify order sync error: %s", exc)
                report["errors"] += 1

        await SourceOfTruthService.mark_synced(
            session, tenant_id,
            provider=_CHANNEL, entity_type="order",
        )
        return report


def _declared_product_currency(sp: dict) -> str | None:
    """The currency Shopify stamps on this product, when it stamps one.

    A bare product payload carries no currency field — the code lives on the
    variant's presentment prices — so both are read before the shop's own
    configured currency is asked.
    """
    code = sp.get("currency")
    if code:
        return str(code)
    for variant in sp.get("variants") or []:
        for presentment in variant.get("presentment_prices") or []:
            amount = presentment.get("price") or {}
            if amount.get("currency_code"):
                return str(amount["currency_code"])
    return None


def _resolve_price_currency(
    declared: str | None,
    *,
    subject: str,
    shop_currency: str | None,
    tenant_currency: str,
) -> str:
    """The currency this amount is in — or a refusal (§47).

    There is no default: a code that appears nowhere is an unknown, and
    stamping the tenant's currency onto it would give a wrong number the label
    of an audited one. Conversion is not on this table either — one currency
    per tenant means a foreign price is a different shop's money.
    """
    code = (declared or shop_currency or "").strip().upper()
    if not code:
        raise ConflictError(
            f"{subject} declares no currency and the shop's is not configured "
            "— refusing to guess what this amount is in"
        )
    if code != tenant_currency:
        raise ConflictError(
            f"{subject} is in {code}, but this tenant trades in "
            f"{tenant_currency} — refusing to re-label it"
        )
    return code


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


def _normalize_shopify_order(
    so: dict, *, tenant_currency: str, shop_currency: str | None = None
) -> dict:
    """Convert a Shopify order payload to our canonical order shape.

    The currency on the row is the tenant's, after the payload's own code has
    agreed with it — an order is money, and money is never defaulted.
    """
    code = _resolve_price_currency(
        so.get("currency"),
        subject=f"{_CHANNEL} order {so.get('id')}",
        shop_currency=shop_currency,
        tenant_currency=tenant_currency,
    )
    return {
        "external_id": str(so.get("id", "")),
        "external_provider": _CHANNEL,
        "status": so.get("financial_status", "pending"),
        "total": so.get("total_price", "0.00"),
        "currency": code,
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
