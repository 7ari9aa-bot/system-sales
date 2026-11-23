"""WhatsApp Flows: the Flow lifecycle on Meta's side, and the reply a customer sends back.

Two separate things live here, and they are separate on Meta's side too:

* the Flow itself — created on the WhatsApp Business Account, given a Flow JSON asset, then
  published. A Flow that is only created is a draft and cannot be sent to a customer.
* the reply — a customer who fills a Flow sends an ordinary inbound message of type
  `interactive`, with `interactive.type == "nfm_reply"` and the answers in `response_json`
  as a JSON *string*. Meta's own warning on that page: the reply carries no Flow id, so the
  `flow_token` we set when sending is the only way to know which Flow it answers.

Shapes are taken from Meta's reference, not memory:
`flows/guides/flowsapi` (create, assets, publish), `flows/guides/sendingaflow` (the interactive
message with `action.name == "flow"`), `flows/guides/flowswebhooks` (the nfm_reply payload).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_WHATSAPP, get_breaker
from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.gateway.base import parse_provider_body

GRAPH_BASE = "https://graph.facebook.com/v27.0"

# Meta's own Flow categories. A category is required at creation and decides the review path.
FLOW_CATEGORIES = frozenset(
    {
        "SIGN_UP",
        "SIGN_IN",
        "APPOINTMENT_BOOKING",
        "LEAD_GENERATION",
        "CONTACT_US",
        "CUSTOMER_SUPPORT",
        "SURVEY",
        "OTHER",
    }
)
FLOW_NAME_MAX = 200
FLOW_TOKEN_MAX = 256
FLOW_CTA_MAX = 30


def check_flow_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ValidationError("a flow needs a name")
    if len(clean) > FLOW_NAME_MAX:
        raise ValidationError(f"a flow name is at most {FLOW_NAME_MAX} characters")
    return clean


def build_flow_message(
    *,
    body: str,
    flow_cta: str,
    flow_id: str | None = None,
    flow_name: str | None = None,
    flow_token: str | None = None,
    screen: str | None = None,
    screen_data: dict | None = None,
    header_text: str | None = None,
    footer_text: str | None = None,
    mode: str | None = None,
) -> dict:
    """The `interactive` object Meta wants for a Flow message.

    One of flow_id or flow_name identifies the Flow (Meta refuses both). `flow_token` is ours:
    it is how the reply is matched back, because the reply itself carries no Flow id.
    """
    if not (flow_id or flow_name):
        raise ValidationError("a flow message needs the flow_id or the flow_name")
    if flow_id and flow_name:
        raise ValidationError("give the flow_id or the flow_name, not both")
    if not (body or "").strip():
        raise ValidationError("a flow message needs its body text")
    cta = (flow_cta or "").strip()
    if not cta or len(cta) > FLOW_CTA_MAX:
        raise ValidationError(f"the flow button label is 1 to {FLOW_CTA_MAX} characters")
    token = (flow_token or "").strip()
    if token and len(token) > FLOW_TOKEN_MAX:
        raise ValidationError(f"a flow token is at most {FLOW_TOKEN_MAX} characters")
    if screen and not screen_data:
        raise ValidationError("opening on a screen needs the data that screen expects")
    mode = (mode or "").lower() or None
    if mode and mode not in {"draft", "published"}:
        raise ValidationError("mode is draft or published")

    parameters: dict[str, Any] = {"flow_message_version": "3", "flow_cta": cta}
    if flow_id:
        parameters["flow_id"] = str(flow_id)
    else:
        parameters["flow_name"] = flow_name
    if token:
        parameters["flow_token"] = token
    if screen:
        # Meta's default action is navigate; data_exchange is for endpoint-driven Flows and is
        # deliberately not offered here, because it needs a Flow JSON built for it.
        parameters["flow_action"] = "navigate"
        parameters["flow_action_payload"] = {"screen": screen, "data": screen_data}
    if mode:
        parameters["mode"] = mode

    interactive: dict[str, Any] = {
        "type": "flow",
        "body": {"text": body},
        "action": {"name": "flow", "parameters": parameters},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}
    return interactive


def parse_flow_reply(interactive: dict | None) -> dict | None:
    """The customer's Flow answers, or None when the message is not a Flow reply.

    `response_json` is a JSON string; a payload that does not parse is reported as
    unreadable rather than silently dropped, so the thread can say so.
    """
    if not isinstance(interactive, dict):
        return None
    if str(interactive.get("type") or "") != "nfm_reply":
        return None
    reply = interactive.get("nfm_reply") or {}
    raw = reply.get("response_json")
    data: dict[str, Any] = {}
    readable = True
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            readable = False
        else:
            if isinstance(parsed, dict):
                data = parsed
            else:
                readable = False
    elif isinstance(raw, dict):
        data = raw
    return {
        "flow_token": data.pop("flow_token", None),
        "data": data,
        "readable": readable,
        "body": reply.get("body"),
    }


def flow_reply_text(reply: dict | None) -> str | None:
    """What the thread shows for a Flow reply: one line per answer, never an invented value."""
    if not reply:
        return None
    if not reply.get("readable"):
        return "وصل رد على النموذج لكن مش قادرين نقراه"
    data = reply.get("data") or {}
    lines = [f"{key}: {value}" for key, value in data.items() if value not in (None, "", [], {})]
    return "\n".join(lines) or None


class WhatsAppFlowsClient:
    """Create, upload, publish and list Flows on a WhatsApp Business Account."""

    def __init__(self, *, base: str = GRAPH_BASE):
        self._base = base

    @staticmethod
    def _token(credentials: dict) -> str:
        token = credentials.get("access_token") or credentials.get("token")
        if not token:
            raise ValidationError("the whatsapp connection has no access token")
        return token

    @staticmethod
    def _waba(credentials: dict) -> str:
        waba = credentials.get("waba_id") or (credentials.get("config") or {}).get("waba_id")
        if not waba:
            raise ValidationError("the whatsapp connection has no business account id")
        return str(waba)

    async def _call(
        self,
        method: str,
        url: str,
        token: str,
        *,
        what: str,
        json_body: dict | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict:
        async def _do() -> dict:
            client = _client or httpx.AsyncClient(timeout=30.0)
            own = _client is None
            try:
                response = await client.request(
                    method, url, headers={"Authorization": f"Bearer {token}"}, json=json_body
                )
            finally:
                if own:
                    await client.aclose()
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"whatsapp {what} failed: {response.status_code} {response.text[:300]}"
                )
            return parse_provider_body(response, f"whatsapp {what}")

        return await get_breaker(PROVIDER_WHATSAPP).call(_do)

    async def create(
        self,
        credentials: dict,
        *,
        name: str,
        categories: list[dict] | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict:
        """Create the Flow. Meta returns `{id, ...}`; it is a DRAFT until it is published."""
        category_list = categories or [{"name": "OTHER"}]
        for item in category_list:
            if str(item.get("name") or "").upper() not in FLOW_CATEGORIES:
                raise ValidationError(
                    "a flow category is one of: " + ", ".join(sorted(FLOW_CATEGORIES))
                )
        data = await self._call(
            "POST",
            f"{self._base}/{self._waba(credentials)}/flows",
            self._token(credentials),
            what="flow create",
            json_body={"name": check_flow_name(name), "categories": category_list},
            _client=_client,
        )
        if not data.get("id"):
            raise ExternalProviderError(f"whatsapp flow create: no id in {str(data)[:200]}")
        return data

    async def upload_asset(
        self,
        credentials: dict,
        *,
        flow_id: str,
        flow_json: dict,
        _client: httpx.AsyncClient | None = None,
    ) -> dict:
        """Attach the Flow JSON. Meta validates it and answers with its own validation errors."""
        if not isinstance(flow_json, dict) or not flow_json:
            raise ValidationError("a flow needs its flow.json")
        return await self._call(
            "POST",
            f"{self._base}/{flow_id}/assets",
            self._token(credentials),
            what="flow asset upload",
            json_body={
                "name": "flow.json",
                "asset_type": "FLOW_JSON",
                "file": json.dumps(flow_json, ensure_ascii=False),
            },
            _client=_client,
        )

    async def publish(
        self, credentials: dict, *, flow_id: str, _client: httpx.AsyncClient | None = None
    ) -> dict:
        return await self._call(
            "POST",
            f"{self._base}/{flow_id}/publish",
            self._token(credentials),
            what="flow publish",
            _client=_client,
        )

    async def list(
        self,
        credentials: dict,
        *,
        limit: int = 100,
        _client: httpx.AsyncClient | None = None,
    ) -> list[dict]:
        data = await self._call(
            "GET",
            f"{self._base}/{self._waba(credentials)}/flows?limit={int(limit)}",
            self._token(credentials),
            what="flow list",
            _client=_client,
        )
        return data.get("data") or []
