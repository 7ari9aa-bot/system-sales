"""Every setting has exactly one home in the Settings Center.

The map (docs/settings/center-map.md) is a navigation contract: twenty sections, each with its
own pages. A key with no declared home is a key nobody can find; a key with two homes is a
setting that can be edited in two places, which is the failure the map forbids in §4.

These assertions are what keeps the registry honest as sections are added: a new key without a
page fails here, and a page filter can never quietly return its neighbour's controls.
"""

from __future__ import annotations

from app.modules.settings.registry import list_definitions

# The twenty section ids of the map, in order. Adding a section is a deliberate change here.
SECTIONS = (
    "account",
    "workspace",
    "team",
    "store",
    "locations",
    "catalog",
    "sales",
    "pos",
    "inventory",
    "purchasing",
    "customers",
    "channels",
    "ai",
    "analytics",
    "automation",
    "notifications",
    "data",
    "security",
    "billing",
    "developers",
)


def test_every_key_has_a_section_and_a_page() -> None:
    homeless = [d.key for d in list_definitions() if not d.home[0] or not d.home[1]]
    assert not homeless, f"registered but no page owns them: {sorted(homeless)}"


def test_every_home_names_a_real_section() -> None:
    unknown = sorted({d.home[0] for d in list_definitions()} - set(SECTIONS))
    assert not unknown, f"home section not in the map: {unknown}"


def test_a_key_is_never_listed_on_two_pages() -> None:
    seen: dict[str, tuple[str, str]] = {}
    for d in list_definitions():
        assert d.key not in seen, f"{d.key} appears twice"
        seen[d.key] = d.home
    # A page filter returns each key at most once, so no screen can render a control twice.
    for section, page in set(seen.values()):
        keys = [d.key for d in list_definitions(section=section, page=page)]
        assert len(keys) == len(set(keys))


def test_the_store_section_owns_the_business_facts() -> None:
    store = {d.key for d in list_definitions(section="store")}
    for key in (
        "business.trade_name",
        "business.phone",
        "business.email",
        "business.legal_name",
        "business.tax_id",
    ):
        assert key in store, f"{key} is not reachable from the store section"


def test_the_business_domain_is_split_across_its_pages() -> None:
    """Contact facts and legal facts are different pages, not one long form."""
    contact = {d.key for d in list_definitions(section="store", page="contact-details")}
    legal = {d.key for d in list_definitions(section="store", page="legal-data")}
    assert "business.phone" in contact
    assert "business.tax_id" in legal
    assert not contact & legal


def test_a_page_filter_narrows_and_an_unknown_page_is_empty() -> None:
    assert list_definitions(section="store", page="contact-details")
    assert list_definitions(section="store", page="no-such-page") == []
    assert list_definitions(section="no-such-section") == []


def test_section_filter_is_a_strict_subset_of_the_registry() -> None:
    everything = list_definitions()
    store = list_definitions(section="store")
    assert store
    assert len(store) < len(everything)
    assert {d.key for d in store} <= {d.key for d in everything}


def test_branch_limits_live_with_the_branches_not_the_business_profile() -> None:
    """They describe the structure, so the locations section owns them."""
    locations = {d.key for d in list_definitions(section="locations")}
    assert "organization.multi_branch" in locations
    assert "organization.max_branches" in locations
    assert "organization.multi_branch" not in {d.key for d in list_definitions(section="store")}


def test_the_return_promise_is_edited_with_the_rest_of_the_policy() -> None:
    """A key's home follows the page that owns the promise, not the module that reads it.

    ``pos.return_max_days`` is read by the till and printed on the receipt, but the owner sets it
    as a promise to customers — so it lives with the policy, and section 07 links here instead of
    offering a second editor for the same rule.
    """
    policies = {d.key for d in list_definitions(section="store", page="business-policies")}
    assert "pos.return_max_days" in policies
    assert "pos.exchange_max_days" in policies
    # It is not also sitting in the till settings.
    till = {d.key for d in list_definitions(section="pos", page="pos-settings")}
    assert "pos.return_max_days" not in till


def test_the_high_impact_keys_say_so() -> None:
    """The page can only warn about what the registry declares."""
    by_key = {d.key: d for d in list_definitions()}
    assert by_key["pos.return_max_days"].impact_level == "high"
    assert by_key["pos.exchange_max_days"].impact_level == "high"


def test_the_catalogue_keys_are_spread_over_the_pages_that_own_them() -> None:
    """Five keys, seven pages: the drawer page must not swallow the others.

    ``product-settings`` owns what a NEW product defaults to; the code shape, the variant limit and
    whether sold-out products show are each a rule of their own page.
    """
    homes = {d.key: d.home for d in list_definitions(section="catalog")}
    assert homes["catalog.sku_format"] == ("catalog", "sku-and-barcode")
    assert homes["catalog.barcode_auto_generate"] == ("catalog", "sku-and-barcode")
    assert homes["catalog.max_variants_per_product"] == ("catalog", "variants-and-options")
    assert homes["catalog.show_out_of_stock"] == ("catalog", "product-states")
    assert homes["catalog.default_tax_rate"] == ("catalog", "product-settings")


def test_the_default_tax_rate_is_high_impact() -> None:
    """A default rate that lands on every new product is money, so the page warns."""
    by_key = {d.key: d for d in list_definitions()}
    assert by_key["catalog.default_tax_rate"].impact_level == "high"


def test_the_tax_keys_that_change_the_charge_are_high_impact() -> None:
    """VAT category and whether prices include VAT change what the customer is charged."""
    by_key = {d.key: d for d in list_definitions()}
    assert by_key["einvoice.vat_category"].impact_level == "high"
    assert by_key["einvoice.prices_include_vat"].impact_level == "high"
    # Still on the tax page, not moved around by the flag.
    assert by_key["einvoice.vat_category"].home == ("sales", "taxes-and-fees")


def test_the_return_windows_have_exactly_one_editing_home() -> None:
    """Section 07's exchange-and-returns page links here; it must not also own the keys."""
    sales_keys = {d.key for d in list_definitions(section="sales")}
    assert "pos.return_max_days" not in sales_keys
    assert "pos.exchange_max_days" not in sales_keys
    policies = {d.key for d in list_definitions(section="store", page="business-policies")}
    assert {"pos.return_max_days", "pos.exchange_max_days"} <= policies


def test_the_till_keys_are_split_by_what_they_decide() -> None:
    """Taking money, closing a drawer and moving cash are three different decisions."""
    homes = {d.key: d.home[1] for d in list_definitions(section="pos")}
    assert homes["pos.take_payments"] == "collection-methods"
    assert homes["pos.settle_payment_methods"] == "collection-methods"
    assert homes["pos.allow_sale_on_account"] == "collection-methods"
    assert homes["pos.reference_required_methods"] == "collection-methods"
    assert homes["pos.variance_reason_required"] == "shifts"
    assert homes["pos.variance_approval_threshold"] == "shifts"
    assert homes["pos.cash_movement_limit"] == "cash-movement"
    # The rest stay on the page that describes how the till behaves.
    assert homes["pos.max_discount_pct"] == "pos-settings"
    assert homes["pos.allow_hold_cart"] == "pos-settings"


def test_the_cash_and_authority_keys_are_high_impact() -> None:
    by_key = {d.key: d for d in list_definitions()}
    for key in (
        "pos.cash_movement_limit",
        "pos.max_discount_pct",
        "pos.variance_approval_threshold",
        "pos.settle_payment_methods",
    ):
        assert by_key[key].impact_level == "high", key


def test_the_inventory_keys_are_spread_over_the_pages_that_own_them() -> None:
    """Twelve keys, six pages: the drawer page must not swallow the rest.

    Classifying stock (reserved, expiring, dead) is a different question from how it is costed,
    and a stocktake needing sign-off is a control, not a display toggle.
    """
    homes = {d.key: d.home for d in list_definitions(section="inventory")}
    assert homes["inventory.auto_reserve"] == ("inventory", "stock-states")
    assert homes["inventory.reserve_ttl_minutes"] == ("inventory", "stock-states")
    assert homes["inventory.expiry_alert_days"] == ("inventory", "stock-states")
    assert homes["inventory.dead_stock_days"] == ("inventory", "stock-states")
    assert homes["inventory.safety_stock_default"] == ("inventory", "stock-limits")
    assert homes["inventory.stocktake_approval_required"] == (
        "inventory",
        "counts-and-adjustments",
    )
    assert homes["inventory.show_warehouse_transfers"] == ("inventory", "transfers")
    assert homes["inventory.quality_check_on_receipt"] == ("inventory", "transfers")
    assert homes["inventory.fifo_enabled"] == ("inventory", "inventory-cost")
    assert homes["inventory.track_locations"] == ("inventory", "inventory-settings")


def test_costing_and_stocktake_sign_off_are_high_impact() -> None:
    """One decides money, the other decides who may move a balance."""
    by_key = {d.key: d for d in list_definitions()}
    assert by_key["inventory.fifo_enabled"].impact_level == "high"
    assert by_key["inventory.stocktake_approval_required"].impact_level == "high"
