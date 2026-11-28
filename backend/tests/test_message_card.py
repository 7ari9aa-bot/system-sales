"""A shared post or a story shows up in the chat as a card, built only from known, safe fields."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.routers.inbox import _present_card


def _m(ig=None, deleted=False):
    raw = {"entry": [{"secret": "token-in-the-raw-body"}]}
    if ig is not None:
        raw["_ig"] = ig
    return SimpleNamespace(payload={"raw": raw}, deleted=deleted)


def test_a_shared_post_becomes_a_card_with_its_link_and_title() -> None:
    card = _present_card(
        _m({"share": {"url": "https://ig/p/1", "title": "New shoes", "kind": "ig_post"}})
    )
    assert card == {
        "type": "share",
        "kind": "ig_post",
        "url": "https://ig/p/1",
        "title": "New shoes",
    }


def test_a_reel_is_marked_as_one_so_the_ui_can_say_so() -> None:
    card = _present_card(_m({"share": {"url": "https://ig/reel/1", "kind": "ig_reel"}}))
    assert card["kind"] == "ig_reel" and card["title"] is None


def test_a_story_reply_and_a_story_mention_are_told_apart() -> None:
    assert (
        _present_card(_m({"story_reply": {"url": "https://cdn/s", "id": "9"}}))["type"]
        == "story_reply"
    )
    assert _present_card(_m({"story_mention": {"url": "https://cdn/s"}}))["type"] == "story_mention"


@pytest.mark.parametrize(
    "bad", ["javascript:alert(1)", "http://plain/x", "data:text/html,x", "//cdn/x", ""]
)
def test_only_https_links_are_ever_sent_to_the_browser(bad) -> None:
    card = _present_card(_m({"share": {"url": bad, "title": "t"}}))
    assert card["url"] is None and card["title"] == "t"


def test_a_bare_text_url_for_a_story_is_accepted() -> None:
    assert _present_card(_m({"story_reply": "https://cdn/s"}))["url"] == "https://cdn/s"


def test_a_long_title_is_cut_and_a_blank_one_is_dropped() -> None:
    assert (
        len(_present_card(_m({"share": {"url": "https://x/1", "title": "a" * 900}}))["title"])
        == 200
    )
    assert _present_card(_m({"share": {"url": "https://x/1", "title": "   "}}))["title"] is None


def test_an_ordinary_message_has_no_card_and_the_raw_body_never_leaks() -> None:
    assert _present_card(_m()) is None
    assert _present_card(SimpleNamespace(payload=None, deleted=False)) is None
    card = _present_card(_m({"share": {"url": "https://x/1"}}))
    assert "token-in-the-raw-body" not in str(card)


def test_garbage_in_the_stored_payload_is_ignored_not_raised() -> None:
    for junk in ({"share": 5}, {"share": ["x"]}, {"story_reply": None}, "not a dict"):
        assert _present_card(SimpleNamespace(payload={"raw": {"_ig": junk}}, deleted=False)) is None


def test_the_messages_endpoint_hides_the_card_of_an_unsent_message() -> None:
    import inspect

    from app.applications.apparel.modules.conversations.routers import inbox

    assert '"card": None if m.deleted else _present_card(m)' in inspect.getsource(inbox)
