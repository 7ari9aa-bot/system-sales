"""What the messages API shows for a cart a customer sent: the checked cart, never the webhook."""

from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.routers.inbox import _present_order


def _m(raw, *, content_type="order", direction="inbound", payload="use-raw"):
    return SimpleNamespace(
        content_type=content_type,
        direction=direction,
        payload={"raw": raw} if payload == "use-raw" else payload,
    )


CART = {
    "id": "wamid.o",
    "type": "order",
    "order": {
        "catalog_id": "c1",
        "text": "hurry",
        "product_items": [
            {"product_retailer_id": "sku-1", "quantity": 2, "item_price": 7.5, "currency": "EGP"}
        ],
    },
}


def test_a_customer_cart_comes_back_checked():
    assert _present_order(_m(CART)) == {
        "catalog_id": "c1",
        "note": "hurry",
        "items": [{"retailer_id": "sku-1", "quantity": 2, "shown_price": 7.5, "currency": "EGP"}],
        "skipped": 0,
    }


def test_the_raw_webhook_never_comes_back():
    raw = {**CART, "secret_token": "LEAK", "order": {**CART["order"], "internal": "LEAK"}}
    assert "LEAK" not in repr(_present_order(_m(raw)))


@pytest.mark.parametrize("content_type", ["text", "unsupported", "interactive", "buttons"])
def test_only_an_order_message_shows_a_cart(content_type):
    assert _present_order(_m(CART, content_type=content_type)) is None


def test_a_cart_we_supposedly_sent_is_never_shown_as_one():
    assert _present_order(_m(CART, direction="outbound")) is None


@pytest.mark.parametrize("payload", [None, {}, [], "x", {"raw": None}, {"raw": "x"}, {"raw": {}}])
def test_a_missing_or_broken_stored_payload_is_none_not_an_error(payload):
    assert _present_order(_m(None, payload=payload)) is None


def test_a_row_whose_cart_no_longer_reads_falls_back_to_none():
    broken = {"type": "order", "order": {"product_items": [{"quantity": 0}]}}
    assert _present_order(_m(broken)) is None
