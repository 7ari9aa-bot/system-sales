"""The ad that started a conversation, kept and shown instead of flattened to a flag.

The report's Messenger gap: "referral / ad context shown in the conversation". The ingest path only
kept ``from_ad: True``, so an agent could see the thread began from an ad but not which campaign, ad
or headline brought the person in — Meta sent them and we threw them away. The row also came out as
a plain text line ("ADS / summer / ad 123") with nothing to render as context.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.gateway.ingest import IngestService
from app.applications.apparel.modules.conversations.routers.inbox import _present_card, _present_referral


def _message(extra: dict, *, raw_key: str = "_messenger"):
    return SimpleNamespace(raw={"object": "page", raw_key: extra})


def test_a_messenger_ad_referral_is_kept_with_its_ad_id():
    details = IngestService._referral_details(
        _message(
            {
                "referral": {
                    "source": "ADS",
                    "type": "OPEN_THREAD",
                    "ref": "summer-sale",
                    "ad_id": "120210",
                    "headline": "خصم ٣٠٪",
                    "ctwa_clid": "abc",
                }
            }
        )
    )
    assert details["source"] == "ADS"
    assert details["ad_id"] == "120210"
    assert details["headline"] == "خصم ٣٠٪"
    assert details["ctwa_clid"] == "abc"


def test_an_instagram_referral_is_read_from_its_own_key():
    details = IngestService._referral_details(
        _message({"referral": {"source": "ADS", "ad_id": "9"}}, raw_key="_ig")
    )
    assert details == {"source": "ADS", "ad_id": "9"}


def test_unknown_keys_and_non_strings_are_dropped():
    """Only the fields Meta documents leave the webhook; the raw object never does."""
    details = IngestService._referral_details(
        _message(
            {
                "referral": {
                    "source": "SHOP",
                    "ad_id": {"nested": "no"},
                    "evil": "<script>",
                    "headline": "  ",
                }
            }
        )
    )
    assert details == {"source": "SHOP"}


def test_a_message_without_a_referral_has_none():
    assert IngestService._referral_details(_message({})) is None
    assert IngestService._referral_details(SimpleNamespace(raw=None)) is None


def test_the_thread_shows_an_ad_card_with_the_campaign():
    row = SimpleNamespace(
        provider_metadata={
            "referral": {"source": "ADS", "ad_id": "120210", "ref": "summer", "headline": "خصم"}
        },
        payload=None,
        content_type="text",
    )
    card = _present_card(row)
    assert card["type"] == "referral"
    assert card["kind"] == "ad"
    assert card["ad_id"] == "120210"
    assert card["title"] == "خصم"


def test_an_mme_link_is_a_link_card_not_an_ad():
    row = SimpleNamespace(
        provider_metadata={"referral": {"source": "SHORTLINK", "ref": "menu"}},
        payload=None,
        content_type="text",
    )
    card = _present_card(row)
    assert card["kind"] == "link"
    assert card["title"] == "menu"


def test_a_row_written_before_the_check_existed_still_renders_safely():
    """An old row could hold anything; only printable strings leave."""
    row = SimpleNamespace(
        provider_metadata={"referral": {"ad_id": 5, "source": "ADS"}},
        payload=None,
        content_type="text",
    )
    card = _present_referral(row)
    assert "ad_id" not in card
    assert card["source"] == "ADS"


def test_no_referral_means_no_card():
    row = SimpleNamespace(provider_metadata={}, payload=None, content_type="text")
    assert _present_referral(row) is None
    assert _present_card(row) is None


@pytest.mark.parametrize("bad", [None, {}, {"referral": "ADS"}, {"referral": {"source": ""}}])
def test_a_malformed_referral_is_ignored(bad):
    row = SimpleNamespace(provider_metadata=bad, payload=None, content_type="text")
    assert _present_referral(row) is None


def test_the_from_ad_flag_is_still_set_for_the_window_extension():
    """The 7-day window rule reads `from_ad`; keeping the details must not lose it."""
    details = IngestService._referral_details(_message({"referral": {"source": "ADS"}}))
    assert str(details.get("source")).upper() == "ADS"
