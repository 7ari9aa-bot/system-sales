"""What a template SEND puts on the wire: header, body, then buttons, exactly as Meta reads them.

A malformed send is refused here with the field named, instead of coming back from Meta as a
generic error after the customer was already counted as contacted.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage
from app.applications.apparel.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.applications.apparel.modules.conversations.gateway.whatsapp_templates import build_send_components as build


def test_no_variables_means_no_components():
    assert build(None) == [] and build({}) == [] and build({"language_code": "en"}) == []


def test_body_variables_keep_their_order_and_become_text_parameters():
    assert build({"body_params": ["Ali", 42, "Cairo"]}) == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Ali"},
                {"type": "text", "text": "42"},
                {"type": "text", "text": "Cairo"},
            ],
        }
    ]


def test_a_text_header_goes_before_the_body():
    out = build({"body_params": ["x"], "header_params": ["Order 7"]})
    assert [c["type"] for c in out] == ["header", "body"]
    assert out[0]["parameters"] == [{"type": "text", "text": "Order 7"}]


@pytest.mark.parametrize("kind", ["image", "video", "document"])
def test_a_media_header_carries_the_link_under_its_own_type(kind):
    out = build({"header_media": {"type": kind, "link": "https://cdn.example/a.bin"}})
    assert out == [
        {
            "type": "header",
            "parameters": [{"type": kind, kind: {"link": "https://cdn.example/a.bin"}}],
        }
    ]


def test_a_document_header_keeps_its_filename():
    out = build(
        {"header_media": {"type": "document", "link": "https://x/y.pdf", "filename": "inv.pdf"}}
    )
    assert out[0]["parameters"][0]["document"] == {"link": "https://x/y.pdf", "filename": "inv.pdf"}


def test_buttons_come_last_in_index_order_whatever_order_they_were_given():
    out = build(
        {
            "body_params": ["x"],
            "button_params": [
                {"index": 1, "type": "url", "text": "order/7"},
                {"index": 0, "type": "quick_reply", "payload": "YES"},
            ],
        }
    )
    assert [c["type"] for c in out] == ["body", "button", "button"]
    assert [c["index"] for c in out[1:]] == ["0", "1"]


def test_button_shapes_match_what_meta_documents():
    out = build(
        {
            "button_params": [
                {"index": 0, "type": "quick_reply", "payload": "CONFIRM_7"},
                {"index": 1, "type": "url", "text": "track/7"},
            ]
        }
    )
    assert out[0] == {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "CONFIRM_7"}],
    }
    assert out[1] == {
        "type": "button",
        "sub_type": "url",
        "index": "1",
        "parameters": [{"type": "text", "text": "track/7"}],
    }


@pytest.mark.parametrize(
    ("vars_", "needle"),
    [
        ({"body_params": ["ok", ""]}, "body_params #2 is empty"),
        ({"body_params": ["ok", "   "]}, "body_params #2 is empty"),
        ({"body_params": ["ok", None]}, "body_params #2 is empty"),
        ({"body_params": "Ali"}, "body_params must be a list"),
        ({"header_params": ["a", "b"]}, "exactly one variable"),
        (
            {"header_params": ["a"], "header_media": {"type": "image", "link": "https://x"}},
            "not both",
        ),
        ({"header_media": {"type": "gif", "link": "https://x"}}, "image, video or document"),
        ({"header_media": {"type": "image", "link": "http://x/a.png"}}, "https"),
        ({"header_media": {"type": "image"}}, "https"),
        ({"header_media": "https://x/a.png"}, "must be an object"),
        ({"button_params": {"index": 0}}, "must be a list"),
        ({"button_params": ["x"]}, "must be an object"),
        ({"button_params": [{"type": "url", "text": "a"}]}, "numeric index"),
        ({"button_params": [{"index": "x", "type": "url", "text": "a"}]}, "numeric index"),
        ({"button_params": [{"index": 10, "type": "url", "text": "a"}]}, "0 to 9"),
        ({"button_params": [{"index": -1, "type": "url", "text": "a"}]}, "0 to 9"),
        (
            {
                "button_params": [
                    {"index": 0, "type": "url", "text": "a"},
                    {"index": 0, "type": "url", "text": "b"},
                ]
            },
            "given twice",
        ),
        ({"button_params": [{"index": 0, "type": "quick_reply"}]}, "needs a payload"),
        (
            {"button_params": [{"index": 0, "type": "quick_reply", "payload": "x" * 257}]},
            "over 256",
        ),
        ({"button_params": [{"index": 0, "type": "url"}]}, "variable text"),
        ({"button_params": [{"index": 0, "type": "url", "text": "x" * 2001}]}, "over 2000"),
        ({"button_params": [{"index": 0, "type": "phone", "text": "1"}]}, "quick_reply or url"),
    ],
)
def test_a_malformed_send_is_refused_with_the_field_named(vars_, needle):
    with pytest.raises(ValidationError, match=needle):
        build(vars_)


def test_the_adapter_puts_the_built_components_in_the_template_payload():
    msg = OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201000000000",
        template_name="order_ready",
        template_vars={
            "language_code": "en",
            "header_media": {"type": "image", "link": "https://cdn.example/p.png"},
            "body_params": ["Ali"],
            "button_params": [{"index": 0, "type": "quick_reply", "payload": "OK"}],
        },
    )
    body = WhatsAppAdapter()._build_send_body(msg)
    assert body["type"] == "template"
    assert body["template"]["name"] == "order_ready"
    assert body["template"]["language"] == {"code": "en"}
    assert [c["type"] for c in body["template"]["components"]] == ["header", "body", "button"]
