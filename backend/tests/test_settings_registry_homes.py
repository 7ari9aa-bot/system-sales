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
