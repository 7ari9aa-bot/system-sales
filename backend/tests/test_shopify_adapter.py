"""§161 Shopify adapter: the sync path must reach a method that EXISTS, in the
tenant's currency (§47).

Why these tests are pure: the two defects they pin are both "fails the first
time it runs".

* ``sync_products`` called ``product_service.upsert_from_external`` — a method
  nothing in the codebase defines. Worse, the call sat inside a bare
  ``except Exception``, so the ``AttributeError`` was swallowed into
  ``report["errors"]`` and the sync returned green with zero rows landed. The
  module that owns products now defines that upsert; the orders path — which
  has no external upsert, and whose owner module this adapter must not import
  (``tests/test_module_boundaries.py``) — refuses with ``NotImplementedError``
  instead of a 3am ``AttributeError``.
* ``_normalize_shopify_order`` defaulted a synced order to the literal
  ``"EGP"``. A tenant trades in one currency (``tenants.currency``, §47), so a
  price arriving in another is refused, never re-labelled.

No network: Shopify's HTTP API sits behind an injected ``httpx.MockTransport``,
and the access token below is a made-up string, never a credential.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import httpx
import pytest

from app.modules.catalog.external import shopify_adapter as sa
from app.modules.catalog.external.shopify_adapter import (
    ShopifyAdapter,
    _normalize_shopify_order,
)
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError

ADAPTER_SOURCE = pathlib.Path(sa.__file__)
TENANT = uuid.uuid4()


# ------------------------------------------------------------------ fakes ----
class _Policy:
    """A tenant policy saying "the external store owns this entity"."""

    def __init__(self, source_mode: str = "external") -> None:
        self.source_mode = source_mode
        self.sync_direction = "inbound"
        self.conflict_policy = "external_wins"
        self.last_synced_at = None
        self.external_version = None


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Answers only what the sync asks: the policy row, the tenant currency."""

    def __init__(self, *, currency: str | None = None, policy: Any = None) -> None:
        self.currency = currency
        self.policy = policy if policy is not None else _Policy()
        self.statements: list[str] = []

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt)
        self.statements.append(sql)
        if "source_of_truth_policies" in sql:
            return _Result(self.policy)
        if "currency" in sql:
            return _Result(self.currency)
        return _Result(None)

    async def flush(self) -> None:
        return None


class _SpyService:
    """Stands in for an application service, recording what it was handed."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    async def upsert_from_external(
        self, session: Any, tenant_id: Any, **kwargs: Any
    ) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)
        return dict(kwargs)


class _NoUpsertService:
    """What the orders side looks like today: no external upsert at all."""


def _product(*, currency: str | None = "EGP", price: str = "19.99", pid: int = 111) -> dict:
    payload: dict[str, Any] = {
        "id": pid,
        "title": "Koshari Bowl",
        "handle": "koshari-bowl",
        "body_html": "<p>practical</p>",
        "status": "active",
        "variants": [{"id": 999, "title": "Default", "price": price, "sku": f"KB-{pid}"}],
    }
    if currency is not None:
        payload["currency"] = currency
    return payload


def _order(*, currency: str | None = "EGP", oid: int = 500) -> dict:
    payload: dict[str, Any] = {
        "id": oid,
        "financial_status": "paid",
        "total_price": "250.00",
        "customer": {"id": 7},
        "line_items": [{"product_id": 111, "variant_id": 999, "quantity": 2, "price": "125.00"}],
    }
    if currency is not None:
        payload["currency"] = currency
    return payload


def _adapter(
    *,
    products: list[dict] | None = None,
    orders: list[dict] | None = None,
    shop_currency: str | None = None,
) -> tuple[ShopifyAdapter, list[str]]:
    """Adapter wired to a fake transport; returns it and the paths it hit."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/products.json"):
            return httpx.Response(200, json={"products": products or []})
        if request.url.path.endswith("/orders.json"):
            return httpx.Response(200, json={"orders": orders or []})
        return httpx.Response(404, json={})

    adapter = ShopifyAdapter(
        shop_domain="demo.myshopify.com",
        access_token="fake-token-not-a-credential",
        transport=httpx.MockTransport(handler),
        shop_currency=shop_currency,
    )
    return adapter, seen


# ------------------------------------------------- defect 1: the dead call ----
def test_catalog_owns_an_external_upsert() -> None:
    """The call site in ``sync_products`` must name a method that exists."""
    assert callable(getattr(CatalogService, "upsert_from_external", None)), (
        "shopify_adapter calls product_service.upsert_from_external(); the "
        "module that owns products has to define it"
    )


async def test_sync_products_lands_what_it_reports() -> None:
    """The report may not swallow the real failure into a green sync."""
    adapter, seen = _adapter(products=[_product()], shop_currency="EGP")
    service = _SpyService()

    report = await adapter.sync_products(
        _FakeSession(), TENANT, product_service=service, tenant_currency="EGP"
    )

    assert report["errors"] == 0
    assert report["conflicts"] == 0
    assert report["synced"] == 1
    assert seen == ["/admin/api/2024-01/products.json"]
    (call,) = service.calls
    assert call["external_ref"] == "111"
    assert call["source"] == "shopify"
    assert call["currency"] == "EGP"
    assert call["data"]["slug"] == "koshari-bowl"
    assert call["data"]["variants"][0]["price"] == "19.99"


async def test_sync_products_defaults_to_the_catalog_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no service injected the sync still has a real owner to write to."""
    recorded: list[dict[str, Any]] = []

    async def _fake_upsert(session: Any, tenant_id: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(CatalogService, "upsert_from_external", staticmethod(_fake_upsert))
    adapter, _seen = _adapter(products=[_product()], shop_currency="EGP")

    report = await adapter.sync_products(_FakeSession(), TENANT, tenant_currency="EGP")

    assert report["synced"] == 1
    assert len(recorded) == 1


async def test_a_service_refusal_is_a_conflict_not_a_lost_row() -> None:
    """The owning service's rejection is reported, not buried in errors."""
    adapter, _seen = _adapter(products=[_product()], shop_currency="EGP")
    service = _SpyService(error=ConflictError("this tenant prices in EGP; a USD price never sells"))

    report = await adapter.sync_products(
        _FakeSession(), TENANT, product_service=service, tenant_currency="EGP"
    )

    assert report["conflicts"] == 1
    assert report["synced"] == 0
    assert report["errors"] == 0


async def test_sync_orders_refuses_loudly_instead_of_attribute_error() -> None:
    """No external order upsert exists — say so, before opening a connection."""
    adapter, seen = _adapter(orders=[_order()], shop_currency="EGP")

    with pytest.raises(NotImplementedError) as excinfo:
        await adapter.sync_orders(
            _FakeSession(),
            TENANT,
            order_service=_NoUpsertService(),
            tenant_currency="EGP",
        )

    message = str(excinfo.value)
    assert "AttributeError" not in message
    assert "upsert_from_external" in message
    assert "shopify" in message
    assert seen == [], "must refuse before fetching, not half-sync"


async def test_sync_orders_proceeds_when_the_service_can_upsert() -> None:
    """The refusal is about a missing capability, not a hardcoded 'never'."""
    adapter, _seen = _adapter(orders=[_order()], shop_currency="EGP")
    service = _SpyService()

    report = await adapter.sync_orders(
        _FakeSession(), TENANT, order_service=service, tenant_currency="EGP"
    )

    assert report["synced"] == 1
    assert service.calls[0]["data"]["currency"] == "EGP"


# ------------------------------------------------- defect 2: "EGP" default ----
def test_the_adapter_carries_no_hardcoded_currency() -> None:
    """§47: the tenant's currency is data, so no literal may stand in for it."""
    assert "EGP" not in ADAPTER_SOURCE.read_text(encoding="utf-8")


def test_normalize_shopify_order_stamps_the_tenants_currency() -> None:
    """A SAR tenant's synced order is a SAR order, whatever the default was."""
    matching = _normalize_shopify_order(_order(currency="SAR"), tenant_currency="SAR")
    assert matching["currency"] == "SAR"
    assert matching["total"] == "250.00"

    # No currency on the payload: the shop's configured currency answers, and
    # it still has to agree with the tenant.
    silent = _normalize_shopify_order(
        _order(currency=None), tenant_currency="SAR", shop_currency="sar"
    )
    assert silent["currency"] == "SAR"


def test_normalize_shopify_order_refuses_a_foreign_currency() -> None:
    with pytest.raises(ConflictError):
        _normalize_shopify_order(_order(currency="USD"), tenant_currency="EGP")


def test_resolve_price_currency_rules() -> None:
    # a matching code passes through, upper-cased
    assert (
        sa._resolve_price_currency("egp", subject="p", shop_currency=None, tenant_currency="EGP")
        == "EGP"
    )
    # nothing declared on the payload: the configured shop currency answers
    assert (
        sa._resolve_price_currency(None, subject="p", shop_currency="EGP", tenant_currency="EGP")
        == "EGP"
    )
    # a different currency is a refusal, not a re-label
    with pytest.raises(ConflictError):
        sa._resolve_price_currency("USD", subject="p", shop_currency=None, tenant_currency="EGP")
    # and an amount with no currency anywhere cannot be guessed at
    with pytest.raises(ConflictError):
        sa._resolve_price_currency(None, subject="p", shop_currency=None, tenant_currency="EGP")


async def test_foreign_currency_price_is_a_conflict_not_a_row() -> None:
    adapter, _seen = _adapter(products=[_product(currency="USD")], shop_currency="USD")
    service = _SpyService()

    report = await adapter.sync_products(
        _FakeSession(), TENANT, product_service=service, tenant_currency="EGP"
    )

    assert report["conflicts"] == 1
    assert report["synced"] == 0
    assert service.calls == []


async def test_price_with_no_currency_anywhere_is_refused() -> None:
    """An unlabelled amount is not the tenant's amount by default."""
    adapter, _seen = _adapter(products=[_product(currency=None)])
    service = _SpyService()

    report = await adapter.sync_products(
        _FakeSession(), TENANT, product_service=service, tenant_currency="EGP"
    )

    assert report["conflicts"] == 1
    assert service.calls == []


async def test_sync_reads_the_tenant_currency_when_nothing_is_injected() -> None:
    """No request scope here, so ``tenants.currency`` is the only answer."""
    adapter, _seen = _adapter(products=[_product(currency="SAR")], shop_currency="SAR")
    service = _SpyService()

    report = await adapter.sync_products(
        _FakeSession(currency="SAR"), TENANT, product_service=service
    )

    assert report["synced"] == 1
    assert service.calls[0]["currency"] == "SAR"


async def test_sync_refuses_a_currency_the_schema_cannot_store() -> None:
    """A three-decimal tenant would lose a minor unit on every price written."""
    adapter, _seen = _adapter(products=[_product(currency="KWD")], shop_currency="KWD")

    with pytest.raises(ValidationError):
        await adapter.sync_products(
            _FakeSession(), TENANT, product_service=_SpyService(), tenant_currency="KWD"
        )
