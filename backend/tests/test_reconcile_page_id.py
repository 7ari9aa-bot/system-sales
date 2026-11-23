"""Which id a reconciliation walks: the Page, never the Instagram account."""

from __future__ import annotations

from app.modules.customers.routers.integrations import reconcile_page_id


def test_a_messenger_channel_walks_the_page_id_the_oauth_callback_stored() -> None:
    assert reconcile_page_id("messenger", {"account_id": "PAGE1"}) == "PAGE1"


def test_an_explicit_page_id_wins() -> None:
    assert reconcile_page_id("messenger", {"page_id": "P2", "account_id": "P1"}) == "P2"


def test_an_instagram_account_id_is_never_taken_for_a_page() -> None:
    assert reconcile_page_id("instagram", {"account_id": "IG1"}) is None
    assert reconcile_page_id("instagram", {"account_id": "IG1", "page_id": "P9"}) == "P9"


def test_a_channel_with_no_id_walks_nothing() -> None:
    assert reconcile_page_id("messenger", {}) is None
