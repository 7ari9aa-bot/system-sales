"""A cart a customer sent from the catalog: read safely, never trusted.

The first payload is Meta's documented one ("Order messages webhook reference"). Everything after
it is a hostile or broken variant, because every byte of this comes from outside.
"""

import math

import pytest

from app.applications.apparel.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.applications.apparel.modules.conversations.gateway.whatsapp_order import (
    MAX_ID,
    MAX_ITEMS,
    MAX_QUANTITY,
    MAX_TEXT,
    order_summary,
    parse_order,
)

pytestmark = pytest.mark.filterwarnings("ignore")


def _msg(**order) -> dict:
    return {"id": "wamid.o", "from": "201001234567", "type": "order", "order": order}


def _line(**kw) -> dict:
    base = {
        "product_retailer_id": "di9ozbzfi4",
        "quantity": 2,
        "item_price": 7.99,
        "currency": "USD",
    }
    base.update(kw)
    return base


# ---- the documented shape


def test_the_documented_payload_is_read_field_for_field():
    cart = parse_order(
        _msg(catalog_id="194836987003835", text="Love these!", product_items=[_line()])
    )
    assert cart == {
        "catalog_id": "194836987003835",
        "note": "Love these!",
        "items": [
            {"retailer_id": "di9ozbzfi4", "quantity": 2, "shown_price": 7.99, "currency": "USD"}
        ],
        "skipped": 0,
    }


def test_several_products_keep_their_order():
    cart = parse_order(
        _msg(product_items=[_line(product_retailer_id=f"p{i}", quantity=i + 1) for i in range(4)])
    )
    assert [(i["retailer_id"], i["quantity"]) for i in cart["items"]] == [
        ("p0", 1),
        ("p1", 2),
        ("p2", 3),
        ("p3", 4),
    ]


def test_the_note_is_optional():
    assert parse_order(_msg(product_items=[_line()]))["note"] == ""


def test_text_is_trimmed():
    cart = parse_order(_msg(text="  hi  ", product_items=[_line(product_retailer_id="  sku-1  ")]))
    assert cart["note"] == "hi"
    assert cart["items"][0]["retailer_id"] == "sku-1"


# ---- not a cart at all


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "x",
        7,
        [],
        {},
        {"type": "text"},
        {"type": "order"},
        {"type": "order", "order": "x"},
        {"type": "order", "order": []},
    ],
)
def test_anything_that_is_not_an_order_message_is_none(bad):
    assert parse_order(bad) is None


@pytest.mark.parametrize("items", [None, "x", 5, {}, []])
def test_a_cart_without_a_product_list_is_none(items):
    assert parse_order(_msg(product_items=items)) is None


def test_a_cart_of_only_broken_lines_is_none_not_an_empty_card():
    assert parse_order(_msg(product_items=[{}, "x", None, _line(quantity=0)])) is None


# ---- one broken line does not hide the rest


def test_a_broken_line_is_dropped_and_counted_so_the_agent_is_not_misled():
    cart = parse_order(
        _msg(
            product_items=[
                _line(),
                _line(product_retailer_id=""),
                "junk",
                _line(product_retailer_id="ok2"),
            ]
        )
    )
    assert [i["retailer_id"] for i in cart["items"]] == ["di9ozbzfi4", "ok2"]
    assert cart["skipped"] == 2


@pytest.mark.parametrize(
    "quantity",
    [0, -1, 1.5, "2", None, True, False, math.nan, math.inf, MAX_QUANTITY + 1, [2], {"n": 2}],
)
def test_a_quantity_that_is_not_a_whole_positive_number_drops_the_line(quantity):
    assert parse_order(_msg(product_items=[_line(quantity=quantity)])) is None


@pytest.mark.parametrize("quantity,expected", [(1, 1), (2.0, 2), (MAX_QUANTITY, MAX_QUANTITY)])
def test_a_whole_quantity_is_kept_even_when_sent_as_a_float(quantity, expected):
    assert (
        parse_order(_msg(product_items=[_line(quantity=quantity)]))["items"][0]["quantity"]
        == expected
    )


@pytest.mark.parametrize("retailer_id", ["", "   ", None, 5, [], {}, True])
def test_a_product_without_a_text_id_is_dropped(retailer_id):
    assert parse_order(_msg(product_items=[_line(product_retailer_id=retailer_id)])) is None


# ---- the customer's price is only shown


@pytest.mark.parametrize(
    "price", [-1, "7.99", None, True, math.nan, math.inf, -math.inf, 10**10, [7]]
)
def test_a_price_that_is_not_a_sane_number_is_left_out_but_the_line_stays(price):
    cart = parse_order(_msg(product_items=[_line(item_price=price)]))
    assert cart["items"][0]["shown_price"] is None
    assert cart["items"][0]["quantity"] == 2


def test_a_free_item_keeps_a_zero_price():
    assert parse_order(_msg(product_items=[_line(item_price=0)]))["items"][0]["shown_price"] == 0.0


@pytest.mark.parametrize(
    "currency,expected",
    [
        ("usd", "USD"),
        ("EGP", "EGP"),
        ("US", ""),
        ("DOLLAR", ""),
        ("U$D", ""),
        ("", ""),
        (None, ""),
        (5, ""),
    ],
)
def test_currency_is_three_letters_or_nothing(currency, expected):
    assert (
        parse_order(_msg(product_items=[_line(currency=currency)]))["items"][0]["currency"]
        == expected
    )


# ---- bounds against a hostile payload


def test_text_and_ids_are_cut_to_their_limits():
    cart = parse_order(
        _msg(
            catalog_id="c" * 5000,
            text="t" * 5000,
            product_items=[_line(product_retailer_id="p" * 5000)],
        )
    )
    assert len(cart["note"]) == MAX_TEXT
    assert len(cart["catalog_id"]) == MAX_ID
    assert len(cart["items"][0]["retailer_id"]) == MAX_ID


def test_an_enormous_cart_is_cut_and_the_rest_counted():
    cart = parse_order(
        _msg(product_items=[_line(product_retailer_id=f"p{i}") for i in range(MAX_ITEMS + 25)])
    )
    assert len(cart["items"]) == MAX_ITEMS
    assert cart["skipped"] == 25


def test_nothing_unexpected_leaves_the_function():
    cart = parse_order(
        _msg(
            catalog_id="c",
            secret="LEAK",
            product_items=[_line(extra="LEAK2")],
            **{"__proto__": "LEAK3"},
        )
    )
    assert "LEAK" not in repr(cart) and "LEAK2" not in repr(cart) and "LEAK3" not in repr(cart)
    assert set(cart) == {"catalog_id", "note", "items", "skipped"}
    assert set(cart["items"][0]) == {"retailer_id", "quantity", "shown_price", "currency"}


def test_markup_in_text_is_kept_as_text_not_interpreted():
    cart = parse_order(_msg(text="<script>alert(1)</script>", product_items=[_line()]))
    assert (
        cart["note"] == "<script>alert(1)</script>"
    )  # escaping is the screen's job; here it is inert data


# ---- the readable summary


def test_summary_is_one_line_per_product_with_no_money():
    cart = parse_order(
        _msg(
            text="Please hurry",
            product_items=[_line(), _line(product_retailer_id="b2", quantity=1)],
        )
    )
    assert order_summary(cart) == "2 x di9ozbzfi4\n1 x b2\nPlease hurry"
    assert "7.99" not in order_summary(cart) and "USD" not in order_summary(cart)


def test_summary_says_when_a_line_could_not_be_read():
    cart = parse_order(_msg(product_items=[_line(), "junk"]))
    assert order_summary(cart).splitlines() == ["2 x di9ozbzfi4", "(+1 unreadable)"]


# ---- through the real adapter


def _payload(msg) -> dict:
    return {
        "entry": [
            {
                "id": "w",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "1"},
                            "contacts": [{"wa_id": "201001234567", "profile": {"name": "Sara"}}],
                            "messages": [msg],
                        },
                    }
                ],
            }
        ]
    }


def test_the_adapter_turns_a_cart_into_an_order_message_with_a_readable_body():
    (m,) = WhatsAppAdapter().parse_inbound(_payload(_msg(catalog_id="c1", product_items=[_line()])))
    assert m.content_type == "order"
    assert m.body == "2 x di9ozbzfi4"
    assert m.raw["order"]["catalog_id"] == "c1"  # the original is still kept for the booking step


def test_the_adapter_keeps_an_unreadable_cart_as_unsupported_and_never_as_an_order():
    (m,) = WhatsAppAdapter().parse_inbound(_payload(_msg(catalog_id="c1")))
    assert m.content_type == "unsupported"


@pytest.mark.parametrize("kind", ["text", "interactive", "image", "", None, "ORDER", "orders"])
def test_a_message_of_another_type_is_never_read_as_a_cart_even_if_it_carries_an_order_field(kind):
    forged = {"type": kind, "order": {"product_items": [_line()]}}
    assert parse_order(forged) is None
