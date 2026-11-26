"""The pricing engine's rules, exercised without a database.

The service's database work is thin (select the live list, select the tier, select the rules), but
the arithmetic and the policy are not: which list wins a tie, when a tier applies, what a cap does
to a discount that exceeds it, and whether an offer that needs a code runs without one. Those are
pure functions over rows, so they are tested directly rather than through a session.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import uuid
from datetime import date
from decimal import Decimal

import pytest


def _load_service():
    """Load the service module without importing the app package (which needs Python 3.12)."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for name, path in (
        ("app", root / "app"),
        ("app.modules", root / "app" / "modules"),
        ("app.modules.pricing", root / "app" / "modules" / "pricing"),
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod
    # The service imports sqlalchemy, its own models and the shared error at module scope. None of
    # the three is needed to test the arithmetic, and this sandbox has no sqlalchemy, so each is
    # replaced with the smallest stand-in that lets the module load.
    errors = types.ModuleType("app.core.errors")

    class ValidationError(Exception):
        pass

    errors.ValidationError = ValidationError
    sys.modules["app.core.errors"] = errors
    core = sys.modules.get("app.core") or types.ModuleType("app.core")
    core.errors = errors
    sys.modules["app.core"] = core

    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.select = lambda *a, **k: None  # the tests never reach a query
    sys.modules["sqlalchemy"] = sqlalchemy
    asyncio_mod = types.ModuleType("sqlalchemy.ext.asyncio")
    asyncio_mod.AsyncSession = object
    ext = types.ModuleType("sqlalchemy.ext")
    ext.asyncio = asyncio_mod
    sys.modules["sqlalchemy.ext"] = ext
    sys.modules["sqlalchemy.ext.asyncio"] = asyncio_mod

    models = types.ModuleType("app.modules.pricing.models")
    models.DISCOUNT_KINDS = ("percent", "amount")
    models.DISCOUNT_SCOPES = ("order", "category", "variant")
    models.DiscountRule = object
    models.PriceList = object
    models.PriceListItem = object
    sys.modules["app.modules.pricing.models"] = models

    spec = importlib.util.spec_from_file_location(
        "pricing_service_under_test", root / "app" / "modules" / "pricing" / "service.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


svc_mod = _load_service()
PricingService = svc_mod.PricingService


class _Rule:
    """The fields the quote reads off a DiscountRule row."""

    def __init__(self, **kw):
        self.id = kw.get("id") or uuid.uuid4()
        self.name = kw.get("name", "rule")
        self.code = kw.get("code")
        self.kind = kw.get("kind", "percent")
        self.value = Decimal(str(kw.get("value", 0)))
        self.scope = kw.get("scope", "order")
        self.target_id = kw.get("target_id")
        self.min_subtotal = kw.get("min_subtotal")
        self.max_discount = kw.get("max_discount")
        self.requires_code = kw.get("requires_code", False)
        self.priority = kw.get("priority", 0)
        self.status = kw.get("status", "active")
        self.starts_on = kw.get("starts_on")
        self.ends_on = kw.get("ends_on")


def _service(settings: dict, rules: list[_Rule]) -> PricingService:
    """A service with the database replaced by the rows the test wants to see."""
    service = PricingService.__new__(PricingService)
    service.tenant_id = uuid.uuid4()

    async def _settings():
        return {k: types.SimpleNamespace(value=v) for k, v in settings.items()}

    async def _rules():
        return rules

    service._settings = _settings  # type: ignore[method-assign]
    service.list_discount_rules = _rules  # type: ignore[method-assign]
    return service


DEFAULTS = {
    "pricing.price_lists_enabled": False,
    "pricing.quantity_tiers_enabled": True,
    "pricing.round_prices_to": "none",
    "pricing.allow_price_below_cost": False,
    "pricing.auto_apply_offers": True,
    "pricing.stacked_discounts": False,
    "pricing.max_order_discount_pct": 50,
}


def _quote(service, lines, code=None, on_date=date(2026, 11, 26)):
    import asyncio

    return asyncio.run(service.quote(lines=lines, code=code, on_date=on_date))


LINE = {"variant_id": uuid.uuid4(), "unit_price": Decimal("100.00"), "quantity": 1}


def test_an_order_wide_percentage_takes_its_share() -> None:
    service = _service(DEFAULTS, [_Rule(kind="percent", value=10)])
    result = _quote(service, [LINE])
    assert result["subtotal"] == Decimal("100.00")
    assert result["discount"] == Decimal("10.00")
    assert result["total"] == Decimal("90.00")


def test_the_order_ceiling_clamps_and_says_it_clamped() -> None:
    """A cap makes the discount smaller; it never refuses the sale."""
    service = _service(
        {**DEFAULTS, "pricing.max_order_discount_pct": 5}, [_Rule(kind="percent", value=40)]
    )
    result = _quote(service, [LINE])
    assert result["discount"] == Decimal("5.00")
    assert result["capped"] is True
    assert result["total"] == Decimal("95.00")


def test_a_rule_cap_bites_before_the_order_cap() -> None:
    service = _service(
        {**DEFAULTS, "pricing.max_order_discount_pct": 100},
        [_Rule(kind="amount", value=80, max_discount=Decimal("15.00"))],
    )
    assert _quote(service, [LINE])["discount"] == Decimal("15.00")


def test_only_the_best_offer_runs_when_stacking_is_off() -> None:
    service = _service(
        DEFAULTS,
        [
            _Rule(name="small", kind="percent", value=5),
            _Rule(name="big", kind="percent", value=20),
        ],
    )
    result = _quote(service, [LINE])
    assert result["discount"] == Decimal("20.00")
    assert len(result["applied"]) == 1


def test_stacking_off_is_the_default_and_stacking_on_adds_up() -> None:
    rules = [
        _Rule(name="a", kind="percent", value=5),
        _Rule(name="b", kind="percent", value=10),
    ]
    one = _quote(_service(DEFAULTS, rules), [LINE])
    both = _quote(_service({**DEFAULTS, "pricing.stacked_discounts": True}, rules), [LINE])
    assert one["discount"] == Decimal("10.00")
    assert both["discount"] == Decimal("15.00")


def test_a_code_gated_offer_does_not_run_without_the_code() -> None:
    service = _service(DEFAULTS, [_Rule(kind="percent", value=10, code="EID", requires_code=True)])
    assert _quote(service, [LINE])["discount"] == Decimal("0.00")
    assert _quote(service, [LINE], code="eid")["discount"] == Decimal("10.00")


def test_auto_apply_off_means_only_what_the_customer_asked_for() -> None:
    service = _service(
        {**DEFAULTS, "pricing.auto_apply_offers": False},
        [
            _Rule(name="open", kind="percent", value=10),
            _Rule(name="coded", kind="percent", value=25, code="VIP", requires_code=True),
        ],
    )
    assert _quote(service, [LINE])["discount"] == Decimal("0.00")
    assert _quote(service, [LINE], code="VIP")["discount"] == Decimal("25.00")


def test_a_scoped_offer_only_touches_its_own_lines() -> None:
    shirt = uuid.uuid4()
    service = _service(
        DEFAULTS, [_Rule(kind="percent", value=50, scope="category", target_id=shirt)]
    )
    lines = [
        {
            "variant_id": uuid.uuid4(),
            "category_id": shirt,
            "unit_price": Decimal("40.00"),
            "quantity": 2,
        },
        {
            "variant_id": uuid.uuid4(),
            "category_id": uuid.uuid4(),
            "unit_price": Decimal("60.00"),
            "quantity": 1,
        },
    ]
    result = _quote(service, lines)
    assert result["subtotal"] == Decimal("140.00")
    assert result["discount"] == Decimal("40.00")


def test_an_expired_offer_does_not_run_and_a_future_one_waits() -> None:
    service = _service(
        DEFAULTS,
        [
            _Rule(name="old", kind="percent", value=10, ends_on=date(2026, 1, 1)),
            _Rule(name="later", kind="percent", value=10, starts_on=date(2027, 1, 1)),
        ],
    )
    assert _quote(service, [LINE])["discount"] == Decimal("0.00")


def test_a_minimum_subtotal_holds_the_offer_back() -> None:
    service = _service(DEFAULTS, [_Rule(kind="percent", value=10, min_subtotal=Decimal("500.00"))])
    assert _quote(service, [LINE])["discount"] == Decimal("0.00")


def test_the_discount_can_never_exceed_the_basket() -> None:
    service = _service(
        {**DEFAULTS, "pricing.max_order_discount_pct": 100}, [_Rule(kind="amount", value=250)]
    )
    result = _quote(service, [LINE])
    assert result["discount"] == Decimal("100.00")
    assert result["total"] == Decimal("0.00")


@pytest.mark.parametrize(
    ("step", "value", "expected"),
    [
        ("none", "10.337", "10.34"),
        ("0.25", "10.30", "10.25"),
        ("0.5", "10.30", "10.50"),
        ("1", "10.60", "11.00"),
    ],
)
def test_rounding_is_applied_to_the_final_unit_price(step: str, value: str, expected: str) -> None:
    assert svc_mod._round_to(Decimal(value), step) == Decimal(expected)


def test_the_quote_reports_whether_below_cost_selling_is_allowed() -> None:
    service = _service({**DEFAULTS, "pricing.allow_price_below_cost": True}, [])
    assert _quote(service, [LINE])["allows_below_cost"] is True
