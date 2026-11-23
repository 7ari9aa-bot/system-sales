"""WhatsApp Flows: the message we send, the reply we receive, and the lifecycle calls.

Shapes come from Meta's own pages: flows/guides/sendingaflow (the interactive flow message),
flows/guides/flowswebhooks (the nfm_reply payload, where response_json is a JSON *string* and
the reply carries no Flow id), flows/guides/flowsapi (create, assets, publish, list).
"""

import json

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.gateway import whatsapp_flows as flows
from app.modules.conversations.gateway.whatsapp_interactive import build_interactive, preview_text
from app.modules.conversations.gateway.whatsapp import WhatsAppAdapter

CREDS = {"access_token": "tok", "waba_id": "waba-1"}


# --- the message we send -------------------------------------------------------------


def test_a_flow_message_carries_meta_flow_action_shape():
    interactive = flows.build_flow_message(
        body="احجز موعدك", flow_cta="ابدأ", flow_id="123", flow_token="order-42"
    )
    assert interactive["type"] == "flow"
    assert interactive["body"] == {"text": "احجز موعدك"}
    action = interactive["action"]
    assert action["name"] == "flow"
    assert action["parameters"] == {
        "flow_message_version": "3",
        "flow_cta": "ابدأ",
        "flow_id": "123",
        "flow_token": "order-42",
    }


def test_a_flow_message_opens_on_a_screen_only_when_it_says_what_that_screen_needs():
    interactive = flows.build_flow_message(
        body="ب", flow_cta="ابدأ", flow_id="1", screen="BOOKING", screen_data={"slot": "10:00"}
    )
    parameters = interactive["action"]["parameters"]
    assert parameters["flow_action"] == "navigate"
    assert parameters["flow_action_payload"] == {"screen": "BOOKING", "data": {"slot": "10:00"}}
    with pytest.raises(ValidationError, match="needs the data"):
        flows.build_flow_message(body="ب", flow_cta="ابدأ", flow_id="1", screen="BOOKING")


def test_a_flow_message_is_identified_by_id_or_name_never_both():
    with pytest.raises(ValidationError, match="flow_id or the flow_name"):
        flows.build_flow_message(body="ب", flow_cta="ابدأ")
    with pytest.raises(ValidationError, match="not both"):
        flows.build_flow_message(body="ب", flow_cta="ابدأ", flow_id="1", flow_name="f")


def test_the_flow_button_label_and_mode_are_checked():
    with pytest.raises(ValidationError, match="button label"):
        flows.build_flow_message(body="ب", flow_cta="", flow_id="1")
    with pytest.raises(ValidationError, match="draft or published"):
        flows.build_flow_message(body="ب", flow_cta="ابدأ", flow_id="1", mode="live")


def test_the_inbox_preview_shows_the_body_and_the_flow_button():
    text = preview_text({"kind": "flow", "body": "احجز موعد", "cta": "ابدأ", "flow_id": "9"})
    assert text == "احجز موعد\n[ ابدأ ]"
    assert build_interactive({"kind": "flow", "body": "ب", "cta": "ج", "flow_id": "9"})["type"] == "flow"


# --- the reply the customer sends ----------------------------------------------------


def _nfm(response_json, body="Sent"):
    return {
        "type": "nfm_reply",
        "nfm_reply": {"name": "flow", "body": body, "response_json": response_json},
    }


def test_a_flow_reply_keeps_its_token_and_answers():
    reply = flows.parse_flow_reply(
        _nfm(json.dumps({"flow_token": "order-42", "name": "أحمد", "slot": "10:00"}))
    )
    assert reply["flow_token"] == "order-42"
    assert reply["data"] == {"name": "أحمد", "slot": "10:00"}
    assert reply["readable"] is True


def test_a_reply_that_is_not_json_is_reported_as_unreadable_not_dropped():
    reply = flows.parse_flow_reply(_nfm("not json"))
    assert reply["readable"] is False
    assert flows.flow_reply_text(reply) == "وصل رد على النموذج لكن مش قادرين نقراه"


def test_a_plain_interactive_message_is_not_a_flow_reply():
    assert flows.parse_flow_reply({"type": "button_reply", "button_reply": {"title": "x"}}) is None
    assert flows.parse_flow_reply(None) is None


def test_the_thread_text_is_one_line_per_answer_and_skips_empties():
    reply = flows.parse_flow_reply(
        _nfm(json.dumps({"flow_token": "t", "name": "أحمد", "note": "", "guests": 2}))
    )
    assert flows.flow_reply_text(reply) == "name: أحمد\nguests: 2"


def test_the_whatsapp_adapter_stores_a_flow_reply_as_its_own_content_type():
    adapter = WhatsAppAdapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "20100", "profile": {"name": "أحمد"}}],
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": "20100",
                                    "type": "interactive",
                                    "interactive": _nfm(
                                        json.dumps({"flow_token": "order-42", "name": "أحمد"})
                                    ),
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    (message,) = adapter.parse_inbound(payload)
    assert message.content_type == "flow"
    assert message.body == "name: أحمد"
    # The structured answers stay in the raw webhook, not only in the flattened text.
    assert message.raw["interactive"]["nfm_reply"]["response_json"]


# --- the lifecycle on Meta's side ----------------------------------------------------


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_create_posts_the_name_and_category_to_the_business_account():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "flow-1"})

    async with _client(handler) as client:
        data = await flows.WhatsAppFlowsClient().create(
            CREDS, name="حجز مواعيد", _client=client
        )
    assert data["id"] == "flow-1"
    assert seen["url"].endswith("/waba-1/flows")
    assert seen["body"] == {"name": "حجز مواعيد", "categories": [{"name": "OTHER"}]}


@pytest.mark.asyncio
async def test_a_flow_category_meta_does_not_accept_is_refused_before_the_call():
    async with _client(lambda r: httpx.Response(200, json={"id": "x"})) as client:
        with pytest.raises(ValidationError, match="flow category"):
            await flows.WhatsAppFlowsClient().create(
                CREDS, name="f", categories=[{"name": "SHOPPING"}], _client=client
            )


@pytest.mark.asyncio
async def test_uploading_the_flow_json_sends_it_as_a_flow_json_asset():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    async with _client(handler) as client:
        await flows.WhatsAppFlowsClient().upload_asset(
            CREDS, flow_id="flow-1", flow_json={"version": "7.0"}, _client=client
        )
    assert seen["url"].endswith("/flow-1/assets")
    assert seen["body"]["asset_type"] == "FLOW_JSON"
    assert seen["body"]["name"] == "flow.json"
    assert json.loads(seen["body"]["file"]) == {"version": "7.0"}


@pytest.mark.asyncio
async def test_publish_is_its_own_call_and_a_refusal_is_surfaced():
    def ok(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/flow-1/publish")
        return httpx.Response(200, json={"success": True})

    async with _client(ok) as client:
        assert await flows.WhatsAppFlowsClient().publish(CREDS, flow_id="flow-1", _client=client)

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "flow has no asset"}})

    async with _client(bad) as client:
        with pytest.raises(ExternalProviderError, match="flow publish failed"):
            await flows.WhatsAppFlowsClient().publish(CREDS, flow_id="flow-1", _client=client)


@pytest.mark.asyncio
async def test_list_reads_the_business_account_flows():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://graph.facebook.com/")
        assert "/waba-1/flows" in str(request.url)
        return httpx.Response(200, json={"data": [{"id": "1", "name": "f"}]})

    async with _client(handler) as client:
        rows = await flows.WhatsAppFlowsClient().list(CREDS, _client=client)
    assert rows == [{"id": "1", "name": "f"}]
