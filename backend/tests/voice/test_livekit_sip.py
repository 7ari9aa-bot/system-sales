"""إعداد SIP: بيتولد صح، بيرفض الإعداد الناقص، وبياخد المتجر من الرقم اللي اتصل عليه."""

from __future__ import annotations

import pytest

from app.platform.voice.runtime.livekit_sip import (
    SipNotConfigured,
    SipRoutingSettings,
    plan_inbound_sip,
    tenant_did_from_call_attributes,
)


class TestPlanInboundSip:
    def test_it_builds_a_trunk_and_a_dispatch_rule_for_our_numbers(self) -> None:
        plan = plan_inbound_sip(
            SipRoutingSettings(dids=("+201234567890",), allowed_addresses=("sip.telco.example",))
        )
        trunk = plan.as_inbound_trunk()["trunk"]
        assert trunk["numbers"] == ["+201234567890"]
        assert trunk["allowed_addresses"] == ["sip.telco.example"]
        rule = plan.as_dispatch_rule()["dispatch_rule"]
        individual = rule["rule"]["dispatch_rule_individual"]
        assert individual["room_prefix"] == "voice-"
        assert individual["room_config"]["agents"] == [{"agent_name": "sales-os-voice"}]
        assert plan.requires_pstn_trunk is True

    def test_a_number_without_a_country_code_is_refused(self) -> None:
        with pytest.raises(SipNotConfigured):
            SipRoutingSettings(dids=("0123456789",), allowed_addresses=("sip.telco.example",))

    def test_no_numbers_means_no_inbound_calls(self) -> None:
        with pytest.raises(SipNotConfigured):
            plan_inbound_sip(SipRoutingSettings(allowed_addresses=("sip.telco.example",)))

    def test_an_open_sip_endpoint_is_refused(self) -> None:
        # Without allowed addresses anyone who learns the URI can ring us and burn credit.
        with pytest.raises(SipNotConfigured):
            plan_inbound_sip(SipRoutingSettings(dids=("+201234567890",)))

    def test_duplicate_numbers_collapse_instead_of_creating_two_trunks_entries(self) -> None:
        plan = plan_inbound_sip(
            SipRoutingSettings(
                dids=("+201234567890", "+201234567890"),
                allowed_addresses=("sip.telco.example", "sip.telco.example"),
            )
        )
        assert plan.numbers == ("+201234567890",)
        assert plan.allowed_addresses == ("sip.telco.example",)


class TestWhichShopWasCalled:
    def test_the_dialled_number_decides_the_shop(self) -> None:
        assert tenant_did_from_call_attributes({"sip.trunkPhoneNumber": "+201234567890"}) == (
            "+201234567890"
        )

    def test_a_call_without_a_dialled_number_is_refused_not_guessed(self) -> None:
        with pytest.raises(SipNotConfigured):
            tenant_did_from_call_attributes({"sip.callID": "abc"})
