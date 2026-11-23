"""WhatsApp Cloud API adapter.

Platform details owned here: signature verification, payload normalization,
media expiry (fetched to durable storage at ingest), 24-hour customer service
window, template sending, rate limits, retries (via worker runtime).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.core.circuit_breaker import PROVIDER_WHATSAPP, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
    parse_provider_body,
)
from app.modules.conversations.gateway.whatsapp_interactive import build_interactive
from app.modules.conversations.gateway.whatsapp_flows import (
    flow_reply_text,
    parse_flow_reply,
)
from app.modules.conversations.gateway.whatsapp_order import order_summary, parse_order
from app.modules.conversations.gateway.whatsapp_templates import build_send_components
from app.modules.conversations.policy import template_language

GRAPH_BASE = "https://graph.facebook.com/v27.0"

# §155: provider media type → canonical Message.content_type. The model
# supports text | image | voice | video | file | location | contact | buttons
# | list | reaction | unsupported — every surface reads THAT column, so the
# adapter (the only component that knows WhatsApp's vocabulary) must set it.
# WhatsApp has no distinct "voice note" type: voice notes arrive as `audio`.
# A sticker is a WebP image; media_type keeps the provider nuance.
_CANONICAL_MEDIA_CONTENT: dict[str, str] = {
    "image": "image",
    "audio": "voice",
    "video": "video",
    "document": "file",
    "sticker": "image",
}


# Stored as the body of a reaction row that withdraws the sender's earlier reaction.
REACTION_REMOVED = "\u2205"


def _short(value: object, limit: int = 60) -> str:
    """A provider-supplied label as short printable text ("" when it is not text at all)."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    return "".join(ch for ch in str(value) if ch.isprintable())[:limit].strip()


def _restriction_detail(event: str, value: dict) -> str:
    """The one phrase that says WHY, from the documented field of each restricting event."""
    if event == "ACCOUNT_RESTRICTION":
        info = value.get("restriction_info")
        first = info[0] if isinstance(info, list) and info and isinstance(info[0], dict) else {}
        return _short(first.get("restriction_type"))
    if event == "DISABLED_UPDATE":
        info = value.get("ban_info")
        return _short(info.get("waba_ban_state")) if isinstance(info, dict) else ""
    info = value.get("violation_info")
    return _short(info.get("violation_type")) if isinstance(info, dict) else ""


class WhatsAppAdapter:
    name = "whatsapp"

    # ---------- webhook auth ----------

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        expected = get_settings().whatsapp_verify_token
        if not expected:
            # Not configured -> cannot verify -> reject (fail closed), exactly
            # like check_signature below and the Telegram adapter. Without this
            # an empty `hub.verify_token` equalled the empty default.
            return None
        provided = query_params.get("hub.verify_token") or ""
        # Constant-time compare on BYTES: compare_digest raises TypeError on
        # non-ASCII str, which would turn a hostile query string into a 500.
        if query_params.get("hub.mode") == "subscribe" and hmac.compare_digest(
            provided.encode(), expected.encode()
        ):
            return query_params.get("hub.challenge", "")
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        secret = get_settings().whatsapp_app_secret
        if not secret:
            # No secret configured → cannot verify; reject (fail closed).
            return False
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        # Compared on BYTES: a str compare_digest raises TypeError on non-ASCII
        # input, which would turn a hostile header into a 500.
        return hmac.compare_digest(signature[7:].encode(), expected.encode())

    # ---------- tenant resolution ----------

    def resolve_tenant_key(self, payload: dict) -> str | None:
        try:
            return payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
        except (KeyError, IndexError, TypeError):
            return None

    def partition_payloads(self, payload: dict) -> list[tuple[str | None, dict]]:
        """Split a Meta envelope by phone number before tenant attribution.

        Meta may batch changes for several phone numbers in one signed
        envelope. Each partition is processed under the tenant that owns that
        phone number, so a batch can never write one merchant's message into
        another merchant's inbox.
        """
        grouped: dict[str | None, list[dict]] = {}
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                phone_number_id = str(metadata.get("phone_number_id") or "").strip()
                grouped.setdefault(phone_number_id or None, []).append(change)

        if len(grouped) == 1 and next(iter(grouped)) is not None:
            return [(next(iter(grouped)), payload)]

        return [
            (
                phone_number_id,
                {
                    **{key: value for key, value in payload.items() if key != "entry"},
                    "entry": [{"changes": changes}],
                },
            )
            for phone_number_id, changes in grouped.items()
        ]

    #: Meta's field name for "a template's review state changed".
    TEMPLATE_STATUS_FIELD = "message_template_status_update"
    #: Account-level news that names the business account and no phone number.
    ACCOUNT_UPDATE_FIELD = "account_update"
    QUALITY_UPDATE_FIELD = "phone_number_quality_update"
    #: Every field whose envelope is placed by business account rather than by phone number.
    ACCOUNT_LEVEL_FIELDS = frozenset(
        {TEMPLATE_STATUS_FIELD, ACCOUNT_UPDATE_FIELD, QUALITY_UPDATE_FIELD}
    )
    #: `account_update` events that mean Meta has limited or switched off the account.
    RESTRICTING_EVENTS = frozenset({"ACCOUNT_RESTRICTION", "DISABLED_UPDATE", "ACCOUNT_VIOLATION"})

    def resolve_template_account(self, payload: dict) -> str | None:
        """The business account id when this envelope is only account-level news.

        Meta's template, account and quality events name the business account (`entry[].id`) and
        carry no phone number, so `resolve_tenant_key` cannot place them. An envelope that mixes
        in anything else, or names several accounts, answers None and keeps its normal routing.
        """
        accounts: set[str] = set()
        for entry in payload.get("entry", []) or []:
            if not isinstance(entry, dict):
                return None
            changes = entry.get("changes") or []
            if not changes or any(
                not isinstance(c, dict) or c.get("field") not in self.ACCOUNT_LEVEL_FIELDS
                for c in changes
            ):
                return None
            account = str(entry.get("id") or "").strip()
            if not account:
                return None
            accounts.add(account)
        return next(iter(accounts)) if len(accounts) == 1 else None

    def has_template_status_change(self, payload: dict) -> bool:
        """True when any change in the envelope reports a template's review state."""
        return any(
            isinstance(change, dict) and change.get("field") == self.TEMPLATE_STATUS_FIELD
            for entry in payload.get("entry", []) or []
            if isinstance(entry, dict)
            for change in entry.get("changes", []) or []
        )

    def parse_account_signals(self, payload: dict) -> list[dict]:
        """What Meta says about the health of the account, reduced to facts we act on.

        Two kinds, both read from fields Meta documents:

        * ``{"kind": "restriction", "event": ..., "detail": ...}`` for `account_update` events
          `ACCOUNT_RESTRICTION` (policy enforcement; `restriction_info[].restriction_type`),
          `DISABLED_UPDATE` (`ban_info.waba_ban_state`) and `ACCOUNT_VIOLATION`
          (`violation_info.violation_type`). Every other `account_update` event (partner sharing,
          pricing tiers, calling quality...) is not a limit on sending and is ignored here.
        * ``{"kind": "limit", "event": ..., "limit": ...}`` for `phone_number_quality_update`,
          which reports throughput / messaging-limit changes. Informational only.

        Values are clipped to short printable text: they end up in a status line, never in a query.
        """
        signals: list[dict] = []
        for entry in payload.get("entry", []) or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []) or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value")
                value = value if isinstance(value, dict) else {}
                field = change.get("field")
                event = _short(value.get("event"))
                if field == self.ACCOUNT_UPDATE_FIELD and event in self.RESTRICTING_EVENTS:
                    signals.append(
                        {
                            "kind": "restriction",
                            "event": event,
                            "detail": _restriction_detail(event, value),
                        }
                    )
                elif field == self.QUALITY_UPDATE_FIELD:
                    limit = value.get("max_daily_conversations_per_business") or value.get(
                        "current_limit"
                    )
                    signals.append({"kind": "limit", "event": event, "limit": _short(limit)})
        return signals

    def split_by_account(self, payload: dict) -> list[dict]:
        """One envelope per phone number, which is how the webhook router asks adapters to split.

        The router resolves the store from the FIRST envelope's key, so without this a delivery
        naming two numbers is filed entirely under the first number's store. `partition_payloads`
        already does the grouping; this exposes it under the name the router looks for.
        """
        return [part for _key, part in self.partition_payloads(payload)]

    # ---------- normalization ----------

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        messages: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {c.get("wa_id"): c for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    wa_id = msg.get("from")
                    contact = contacts.get(wa_id, {})
                    profile_name = (contact.get("profile") or {}).get("name")
                    body, media_url, media_type, content_type = self._extract_content(msg)
                    messages.append(
                        InboundMessage(
                            channel=self.name,
                            channel_message_id=msg.get("id"),
                            customer_ref=wa_id or "",
                            customer_name=profile_name,
                            body=body,
                            media_url=media_url,
                            media_type=media_type,
                            content_type=content_type,
                            reply_to_message_id=self._reply_context(msg),
                            raw=msg,
                        )
                    )
        return messages

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        updates: list[StatusUpdate] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status in value.get("statuses", []):
                    errors = status.get("errors") or []
                    first = errors[0] if errors and isinstance(errors[0], dict) else {}
                    code = first.get("code")
                    title = first.get("title") or first.get("message")
                    details = (first.get("error_data") or {}).get("details") or first.get("details")
                    # The stored error keeps Meta's code in front of its text, because the row has
                    # one text column and the code is what support and the merchant search for.
                    text = first.get("message") or title
                    if text and code is not None:
                        text = f"{code}: {text}"
                    if text and details and details not in text:
                        text = f"{text} ({details})"
                    updates.append(
                        StatusUpdate(
                            channel_message_id=status.get("id", ""),
                            status=status.get("status", ""),
                            error=text,
                            timestamp=status.get("timestamp"),
                            error_code=code if isinstance(code, int) else None,
                            error_title=title,
                            error_details=details,
                        )
                    )
        return updates

    def _extract_content(self, msg: dict) -> tuple[str | None, str | None, str | None, str]:
        """Normalize one provider message.

        Returns (body, media_url, media_type, canonical content_type). The
        content type is §155's whole point: a voice note is `voice`, a document
        is `file`, a button tap is `buttons` — never degraded to plain text.
        """
        msg_type = msg.get("type")
        if msg_type == "text":
            return msg.get("text", {}).get("body"), None, None, "text"
        if msg_type in _CANONICAL_MEDIA_CONTENT:
            media = msg.get(msg_type, {})
            return (
                msg.get("caption"),
                media.get("link") or media.get("id"),
                msg_type,
                _CANONICAL_MEDIA_CONTENT[msg_type],
            )
        if msg_type == "location":
            loc = msg.get("location", {})
            return (
                f"📍 {loc.get('name') or ''} {loc.get('address') or ''}".strip(),
                None,
                None,
                "location",
            )
        if msg_type == "contacts":
            return self._contact_body(msg.get("contacts")), None, None, "contact"
        if msg_type == "button":
            # A tap on a template quick-reply button.
            return msg.get("button", {}).get("text"), None, None, "buttons"
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            button_reply = interactive.get("button_reply")
            if button_reply is not None:
                return button_reply.get("title"), None, None, "buttons"
            list_reply = interactive.get("list_reply")
            if list_reply is not None:
                return list_reply.get("title"), None, None, "list"
            if str(interactive.get("type") or "") == "nfm_reply":
                # A filled WhatsApp Flow. The answers are in response_json (a JSON string);
                # the raw webhook keeps them structured, and the thread gets one line each.
                reply = parse_flow_reply(interactive)
                return flow_reply_text(reply), None, None, "flow"
            return None, None, None, "unsupported"
        if msg_type == "reaction":
            # WhatsApp removes a reaction by sending an EMPTY emoji. A message
            # row needs a body, so a removal is stored as an explicit marker
            # rather than "" (which add_message rejects, failing the webhook).
            emoji = (msg.get("reaction", {}).get("emoji") or "").strip()
            return emoji or REACTION_REMOVED, None, None, "reaction"
        if msg_type == "order":
            # A cart sent from our catalog. Shown as a readable list, never as the raw webhook.
            # One with no readable product at all falls through to "unsupported" below.
            cart = parse_order(msg)
            if cart is not None:
                return order_summary(cart), None, None, "order"
        # A type this adapter does not know (an order with nothing readable, system, referral,
        # ...): the raw JSON is kept as the body for forensics, and the canonical type is
        # honest about it instead of claiming "text".
        return (json.dumps(msg)[:500] if msg else None, None, None, "unsupported")

    @staticmethod
    def _contact_body(contacts: list | None) -> str | None:
        """First shared contact as a short human-readable body (§155)."""
        first = contacts[0] if contacts else None
        if not isinstance(first, dict):
            return "[contacts]"
        name = (first.get("name") or {}).get("formatted_name")
        phones = first.get("phones") or []
        phone = (phones[0] or {}).get("phone") if phones else None
        return " ".join(part for part in (name, phone) if part) or "[contacts]"

    @staticmethod
    def _reply_context(msg: dict) -> str | None:
        """§155 threading: the provider id this message replies to.

        Every reply-shaped payload carries `context.id` (a quoted message,
        a button tap quoting the template, a reaction quoting its target).
        """
        context = msg.get("context") or {}
        return context.get("id") or (msg.get("reaction") or {}).get("message_id")

    # ---------- outbound ----------

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Send directly to the WhatsApp Cloud API.

        ``_client`` is an injection point for tests (MockTransport).
        """
        phone_number_id = credentials.get("phone_number_id")
        token = credentials.get("access_token")
        if not phone_number_id or not token:
            raise ExternalProviderError("whatsapp integration missing credentials")

        body_payload = self._build_send_payload(message)

        async def _post() -> str:
            """Post and return the provider message id — entirely inside the breaker."""
            url = f"{GRAPH_BASE}/{phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {token}"}
            if _client is not None:
                response = await _client.post(url, headers=headers, json=body_payload)
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, headers=headers, json=body_payload)

            # A provider that REJECTS the send is a provider FAILURE, so it must be
            # raised INSIDE the breaker. Wrapping only the request meant a provider
            # answering 500 to every call was recorded as a SUCCESS and the breaker
            # never opened — the single case it exists for.
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"whatsapp send failed: {response.status_code} {response.text[:200]}"
                )
            # A 2xx is not proof of acceptance either: Graph answers 200 with an
            # `error` object, and an intermediary can answer 200 with HTML. Both
            # must be raised here too, or they count as breaker SUCCESSES.
            data = parse_provider_body(response, "whatsapp send")
            try:
                message_id = data["messages"][0]["id"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExternalProviderError(
                    f"whatsapp send: no message id in response: {str(data)[:200]}"
                ) from exc
            if not message_id:
                raise ExternalProviderError("whatsapp send: empty message id in response")
            return str(message_id)

        # §47: the outbound call goes through the process-wide `provider.whatsapp`
        # breaker, so a dead provider is backed off instead of hammered. An OPEN
        # breaker raises CircuitOpenError; deciding whether that retries, defers or
        # fails is the caller's job, not the adapter's.
        return await get_breaker(PROVIDER_WHATSAPP).call(_post)

    @staticmethod
    def build_read_signal(provider_message_id: str, *, typing: bool) -> dict:
        """The Cloud API body that marks a customer's message read (blue ticks on
        THEIR phone) and, optionally, shows them "typing…".

        It is ONE request: ``status: read`` plus ``typing_indicator``. Meta also
        marks every earlier message in the conversation read, and clears the
        indicator after 25 seconds or when we reply, whichever is first.
        """
        body: dict = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": provider_message_id,
        }
        if typing:
            body["typing_indicator"] = {"type": "text"}
        return body

    async def send_read_signal(
        self,
        credentials: ProviderCredentials,
        provider_message_id: str,
        *,
        typing: bool,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        """Tell WhatsApp the customer's message was read, and optionally that we are typing.

        Same rules as ``send``: it goes through the ``provider.whatsapp`` breaker, a
        provider rejection is raised INSIDE it, and a 200 carrying an ``error`` body
        is a failure too. The caller decides whether a failure matters; for a
        courtesy signal it never should block the agent.
        """
        phone_number_id = credentials.get("phone_number_id")
        token = credentials.get("access_token")
        if not phone_number_id or not token:
            raise ExternalProviderError("whatsapp integration missing credentials")
        if not provider_message_id:
            raise ExternalProviderError("whatsapp read signal: no message id")
        body_payload = self.build_read_signal(provider_message_id, typing=typing)

        async def _post() -> None:
            url = f"{GRAPH_BASE}/{phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {token}"}
            if _client is not None:
                response = await _client.post(url, headers=headers, json=body_payload)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(url, headers=headers, json=body_payload)
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"whatsapp read signal failed: {response.status_code} {response.text[:200]}"
                )
            data = parse_provider_body(response, "whatsapp read signal")
            if data.get("success") is not True:
                raise ExternalProviderError(f"whatsapp read signal not accepted: {str(data)[:200]}")

        await get_breaker(PROVIDER_WHATSAPP).call(_post)

    def _build_send_payload(self, message: OutboundMessage) -> dict:
        # A reaction is its own message type: it names the target by provider id
        # and carries only the emoji (an empty one withdraws the reaction). It is
        # never a quoted reply, so it returns before the context block below.
        if message.meta.get("reaction_to_provider_id"):
            emoji = message.body or ""
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": message.customer_ref,
                "type": "reaction",
                "reaction": {
                    "message_id": message.meta["reaction_to_provider_id"],
                    "emoji": "" if emoji == REACTION_REMOVED else emoji,
                },
            }
        payload = self._build_send_body(message)
        # A quoted reply. Templates are never replies (they open a conversation
        # outside the window), so they are left exactly as they were.
        reply_to = message.meta.get("reply_to_provider_id")
        if reply_to and payload.get("type") != "template":
            payload["context"] = {"message_id": reply_to}
        return payload

    def _build_send_body(self, message: OutboundMessage) -> dict:
        base = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": message.customer_ref,
        }
        # An interactive message (buttons, list, link button). The spec was validated when the
        # agent composed it; it is built again here so that what reaches Meta is always a freshly
        # checked object and never a stored dict trusted as-is.
        interactive = message.meta.get("interactive")
        if interactive and not message.template_name:
            return {**base, "type": "interactive", "interactive": build_interactive(interactive)}
        if message.template_name:
            lang = template_language(message.template_vars)
            components = build_send_components(message.template_vars)
            return {
                **base,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": lang},
                    "components": components,
                },
            }
        if message.media_url:
            media_type = message.meta.get("media_type", "image")
            media_block: dict = {"link": message.media_url}
            if media_type == "document":
                media_block["filename"] = message.meta.get("filename", "file")
            # The Cloud API takes the caption INSIDE the media object, and only
            # for images, videos and documents: audio and stickers reject one.
            if message.body and media_type in ("image", "video", "document"):
                media_block["caption"] = message.body
            return {**base, "type": media_type, media_type: media_block}
        return {**base, "type": "text", "text": {"preview_url": True, "body": message.body or ""}}


whatsapp_adapter = WhatsAppAdapter()
