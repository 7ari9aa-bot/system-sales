"""The WhatsApp features Meta gates, and the coexistence choice at signup.

The report's WhatsApp gaps (a) and (g). Two failure modes this file pins down:

* **a dead button**: Calls / Groups / Marketing Messages offered as switches FIHRIST cannot flip.
  They are now declared with a state, Meta's own eligibility rule, and what the owner can do.
* **a false green**: `coexistence` used to be declared plain AVAILABLE while nothing in signup
  handled the coexistence step at all. It now reports what actually happened.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.applications.apparel.modules.customers import whatsapp_roadmap as roadmap
from app.applications.apparel.modules.customers.capability_states import (
    ACCOUNT_INELIGIBLE,
    AVAILABLE,
    NEEDS_APP_REVIEW,
    REGION_RESTRICTED,
    STATES,
    evaluate,
)
from app.applications.apparel.modules.customers.meta_whatsapp_signup import WhatsAppSignupCompleteBody


def test_every_gated_feature_is_declared_with_evidence_and_an_action():
    rows = roadmap.roadmap()
    keys = {row["key"] for row in rows}
    assert {"coexistence", "calls", "groups", "marketing_messages"} == keys
    for row in rows:
        assert row["state"] in STATES, row["key"]
        assert row["eligibility"] and row["evidence"] and row["action"], row["key"]
        assert row["title"]


def test_no_gated_feature_claims_to_be_available_out_of_the_box():
    """Calls, Groups and Marketing Messages are Meta's decision, never ours."""
    by_key = {row["key"]: row for row in roadmap.roadmap()}
    assert by_key["calls"]["state"] == REGION_RESTRICTED
    assert by_key["groups"]["state"] == ACCOUNT_INELIGIBLE
    assert by_key["marketing_messages"]["state"] == NEEDS_APP_REVIEW


def test_the_capability_report_carries_the_roadmap_states_not_a_false_green():
    rows = {
        row["key"]: row
        for row in evaluate(
            "whatsapp",
            connected=True,
            granted_scopes=set(),
            subscription_fields=set(),
            seen_fields=set(),
        )
    }
    # Nobody has asked Meta, so nobody has refused: not_requested, never account_ineligible.
    assert rows["coexistence"]["state"] == "not_requested"
    assert "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING" in (rows["coexistence"]["reason"] or "")
    assert rows["calls"]["state"] == REGION_RESTRICTED
    assert rows["groups"]["state"] == ACCOUNT_INELIGIBLE
    assert rows["marketing_messages"]["state"] == NEEDS_APP_REVIEW
    # Built is not ready: with no Flow / catalog fact measured they are unverified, not green.
    assert rows["flows"]["state"] == "no_live_event_verified"
    assert rows["catalog_messages"]["state"] == "no_live_event_verified"


def test_a_measured_state_only_replaces_a_known_one():
    measured = roadmap.state_for("coexistence", measured=AVAILABLE)
    assert measured["state"] == AVAILABLE and measured["measured"] is True
    unknown = roadmap.state_for("coexistence", measured="totally_fine")
    assert unknown["state"] == "not_requested"
    assert "measured" not in unknown


def test_an_unknown_feature_is_a_key_error_not_a_blank_badge():
    with pytest.raises(KeyError):
        roadmap.state_for("teleportation")


def test_the_signup_asks_for_coexistence_by_default():
    """The channel's target journey is a number that already runs the WhatsApp Business app.

    The popup therefore asks Meta for the Business App flow unless a caller says otherwise; the
    stored mode is still decided from Meta's own answer (see test_whatsapp_coexistence_onboarding).
    """
    body = WhatsAppSignupCompleteBody(
        code="abcdefgh", waba_id="123", phone_number_id="456", onboarding_mode="coexistence"
    )
    assert body.onboarding_mode == "coexistence"
    default = WhatsAppSignupCompleteBody(code="abcdefgh", waba_id="123", phone_number_id="456")
    assert default.onboarding_mode == "coexistence"
    explicit = WhatsAppSignupCompleteBody(
        code="abcdefgh", waba_id="123", phone_number_id="456", onboarding_mode="cloud_api"
    )
    assert explicit.onboarding_mode == "cloud_api"


def test_a_made_up_onboarding_mode_is_refused():
    """A typo must not be stored as if it were a connection mode."""
    with pytest.raises(ValidationError):
        WhatsAppSignupCompleteBody(
            code="abcdefgh", waba_id="123", phone_number_id="456", onboarding_mode="coexisting"
        )
