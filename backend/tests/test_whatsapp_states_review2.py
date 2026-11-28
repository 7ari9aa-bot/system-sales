"""WhatsApp states that must not claim more (or less) than was measured."""

from __future__ import annotations

from app.applications.apparel.modules.customers import capability_states as cs
from app.applications.apparel.modules.customers import whatsapp_roadmap as rm
from app.applications.apparel.modules.customers.meta_linking import MetaPageConnection


def _state(rows, key):
    return next(r["state"] for r in rows if r["key"] == key)


def _eval(**facts):
    return cs.evaluate("whatsapp", connected=True, subscription_fields=set(), facts=facts or None)


def test_flows_and_catalog_are_not_available_just_because_whatsapp_is_connected() -> None:
    rows = _eval()
    assert _state(rows, "flows") == cs.NO_LIVE_EVENT_VERIFIED
    assert _state(rows, "catalog_messages") == cs.NO_LIVE_EVENT_VERIFIED


def test_flows_and_catalog_become_available_only_on_evidence() -> None:
    rows = _eval(flows_ready=True, catalog_ready=True)
    assert _state(rows, "flows") == cs.AVAILABLE
    assert _state(rows, "catalog_messages") == cs.AVAILABLE


def test_a_missing_flow_or_catalog_is_reported_as_not_set_up() -> None:
    rows = _eval(flows_ready=False, catalog_ready=False)
    assert _state(rows, "flows") == cs.NOT_REQUESTED
    assert _state(rows, "catalog_messages") == cs.NOT_REQUESTED


def test_coexistence_states_are_distinct_and_honest() -> None:
    # A plain Cloud API connection never asked: not a refusal.
    assert rm.coexistence_state({"onboarding_mode": "cloud_api"}) == rm.NOT_REQUESTED
    assert rm.coexistence_state({}) == rm.NOT_REQUESTED
    # Connected through coexistence: Meta already allowed it.
    assert rm.coexistence_state({"onboarding_mode": "coexistence"}) == rm.AVAILABLE
    # Asked, no answer yet.
    assert rm.coexistence_state({"coexistence_requested": True}) == rm.ELIGIBILITY_UNKNOWN
    # Only Meta's own refusal makes the account ineligible.
    assert rm.coexistence_state({"coexistence_refused": True}) == rm.ACCOUNT_INELIGIBLE


def test_every_new_state_is_one_the_ui_and_registry_know() -> None:
    for state in (rm.NOT_REQUESTED, rm.ELIGIBILITY_UNKNOWN):
        assert state in rm.ROADMAP_STATES
        assert state in cs.STATES


def test_the_declared_coexistence_state_is_not_a_refusal() -> None:
    assert rm.ROADMAP["coexistence"]["state"] == rm.NOT_REQUESTED


def test_the_connection_carries_whatsapp_facts_only_when_recorded() -> None:
    from types import SimpleNamespace

    def row(config):
        return SimpleNamespace(
            provider="whatsapp",
            config=config,
            status="active",
            credentials={"k": 1},
            webhook_health=None,
        )

    assert MetaPageConnection.from_integration(row({})).facts == {}
    facts = MetaPageConnection.from_integration(row({"published_flows": 2, "catalog_id": ""})).facts
    assert facts == {"flows_ready": True, "catalog_ready": False}
