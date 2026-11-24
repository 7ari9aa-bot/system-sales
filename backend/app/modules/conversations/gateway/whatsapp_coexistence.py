"""WhatsApp Business App coexistence payloads: contacts, chat history, the merchant's own replies.

Three webhook fields exist ONLY for a number that runs on the WhatsApp Business app and the Cloud
API together, and none of them is a customer turn:

* ``smb_app_state_sync`` — the app's WhatsApp contacts, and every later add/update/remove.
* ``history`` — up to 180 days of one-to-one chat history, in three phases, each split into chunks
  that may arrive in any order and more than once.
* ``smb_message_echoes`` — what the merchant typed in the app on their phone.

They are parsed here, apart from ``parse_inbound``, because they must never be fed to the live
message path: a thousand imported messages would each look like a new customer question and the
agent would answer all of them. Everything in this module is pure — a payload in, plain dicts out —
so the shapes Meta sends can be pinned by tests that need no database.

Meta's exact nesting differs between the three fields and has changed across releases, so every
reader below looks for the documented keys first and tolerates the older/alternative ones rather
than dropping the batch on the floor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

#: Provider media type → canonical ``Message.content_type``. WhatsApp has no distinct "voice note"
#: type (voice notes arrive as ``audio``) and a sticker is a WebP image, so ``media_type`` keeps the
#: provider nuance while ``content_type`` is what every screen reads.
CANONICAL_MEDIA_CONTENT: dict[str, str] = {
    "image": "image",
    "audio": "voice",
    "video": "video",
    "document": "file",
    "sticker": "image",
}

#: Meta's error code for "this message cannot be delivered to the partner" — the usual cause on a
#: coexistence number is a first message from a companion device that is not supported. It is a
#: known, explainable gap, never a broken channel.
UNSUPPORTED_MESSAGE_CODE = 131060


def extract_content(msg: dict) -> tuple[str | None, str | None, str | None, str]:
    """(body, media_url, media_type, canonical content_type) for one provider message.

    Shared by the live parser and by the history/echo readers: a voice note imported from history
    has to look exactly like a voice note that arrived a minute ago, or the inbox shows two kinds
    of the same thing.
    """
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body"), None, None, "text"
    if msg_type in CANONICAL_MEDIA_CONTENT:
        media = msg.get(msg_type, {}) or {}
        return (
            msg.get("caption"),
            media.get("link") or media.get("id"),
            msg_type,
            CANONICAL_MEDIA_CONTENT[msg_type],
        )
    if msg_type == "location":
        loc = msg.get("location", {}) or {}
        return (
            f"📍 {loc.get('name') or ''} {loc.get('address') or ''}".strip(),
            None,
            None,
            "location",
        )
    if msg_type == "contacts":
        return contact_body(msg.get("contacts")), None, None, "contact"
    if msg_type == "button":
        return (msg.get("button") or {}).get("text"), None, None, "buttons"
    if msg_type == "interactive":
        interactive = msg.get("interactive") or {}
        button_reply = interactive.get("button_reply")
        if button_reply is not None:
            return button_reply.get("title"), None, None, "buttons"
        list_reply = interactive.get("list_reply")
        if list_reply is not None:
            return list_reply.get("title"), None, None, "list"
        if str(interactive.get("type") or "") == "nfm_reply":
            # A filled WhatsApp Flow: the answers live in response_json, and the thread gets one
            # readable line each. Imported here because the flow module is a sibling reader.
            from app.modules.conversations.gateway.whatsapp_flows import (
                flow_reply_text,
                parse_flow_reply,
            )

            return flow_reply_text(parse_flow_reply(interactive)), None, None, "flow"
        return None, None, None, "unsupported"
    if msg_type == "reaction":
        emoji = (msg.get("reaction") or {}).get("emoji") or ""
        # An empty emoji withdraws the reaction; the row needs a body, so it gets a marker.
        return emoji.strip() or "\u2205", None, None, "reaction"
    if msg_type == "order":
        # A cart sent from our catalog, shown as a readable list rather than the raw webhook.
        from app.modules.conversations.gateway.whatsapp_order import order_summary, parse_order

        cart = parse_order(msg)
        if cart is not None:
            return order_summary(cart), None, None, "order"
    # A type this reader does not know: keep the raw JSON for forensics and be honest about it
    # instead of claiming it was text.
    return (json.dumps(msg)[:500] if msg else None, None, None, "unsupported")


def contact_body(contacts: list | None) -> str | None:
    """First shared contact as a short human-readable body."""
    first = contacts[0] if contacts else None
    if not isinstance(first, dict):
        return "[contacts]"
    name = (first.get("name") or {}).get("formatted_name")
    phones = first.get("phones") or []
    phone = (phones[0] or {}).get("phone") if phones else None
    return " ".join(part for part in (name, phone) if part) or "[contacts]"


def reply_context(msg: dict) -> str | None:
    """The provider id this message replies to (``context.id`` on every reply-shaped payload)."""
    context = msg.get("context") or {}
    return context.get("id") or (msg.get("reaction") or {}).get("message_id")


def occurred_at(value: object) -> datetime | None:
    """Meta's epoch-seconds timestamp as an aware UTC datetime, or None when it is unusable."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
    elif isinstance(value, str) and value.strip().isdigit():
        seconds = float(value.strip())
    else:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _changes(payload: dict, field: str) -> list[dict]:
    """Every ``value`` object for one webhook field, in envelope order."""
    out: list[dict] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict) or change.get("field") != field:
                continue
            value = change.get("value")
            out.append(value if isinstance(value, dict) else {})
    return out


def _phone_number_id(value: dict) -> str:
    metadata = value.get("metadata") or {}
    return str(metadata.get("phone_number_id") or "").strip()


def _request_id(value: dict) -> str | None:
    for key in ("request_id", "requestId", "sync_request_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


# ---------- history ----------


def _threads(value: dict) -> list[dict]:
    """The conversation threads inside one history chunk, in whichever shape Meta sent them.

    Documented shape: ``history: [{threads: [...]}]``; some releases put ``threads`` directly on the
    value, and a single-thread batch carries ``messages`` without a thread wrapper.
    """
    threads: list[dict] = []
    for key in ("threads", "history", "chats"):
        container = value.get(key)
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, dict):
                continue
            nested = item.get("threads")
            if isinstance(nested, list):
                threads.extend(t for t in nested if isinstance(t, dict))
            elif item.get("id") or item.get("messages"):
                threads.append(item)
    if not threads and isinstance(value.get("messages"), list):
        metadata = value.get("metadata") or {}
        threads.append(
            {
                "id": metadata.get("wa_id") or metadata.get("phone_number"),
                "messages": value["messages"],
            }
        )
    return threads


def _normalize_thread_message(msg: dict, thread_id: str, business_number: str) -> dict | None:
    """One historical message as the backfill path stores it."""
    if not isinstance(msg, dict):
        return None
    sender = str(msg.get("from") or "").strip()
    # The thread id is the CUSTOMER. A message whose sender is the thread itself came from the
    # customer; anything else (the business number, or a device of theirs) was sent out.
    direction = "inbound" if sender and sender == thread_id else "outbound"
    body, media_url, media_type, content_type = extract_content(msg)
    if not body and not media_url and content_type != "unsupported":
        return None
    return {
        "channel_message_id": str(msg.get("id") or "").strip() or None,
        "customer_ref": thread_id,
        "direction": direction,
        "occurred_at": occurred_at(msg.get("timestamp")),
        "body": body,
        "media_url": media_url,
        "media_type": media_type,
        "content_type": content_type,
        "reply_to_message_id": reply_context(msg),
        "raw": msg,
    }


def parse_history_batches(payload: dict) -> list[dict]:
    """Normalized history chunks, each with its own phase/chunk_order/progress.

    ``progress`` reaching 100 is Meta saying the whole transfer is done — the only signal that may
    move the channel to READY. A chunk with no messages still carries its progress and is returned:
    dropping it would lose the completion signal of the last phase.
    """
    batches: list[dict] = []
    for value in _changes(payload, "history"):
        metadata = value.get("metadata") or {}
        business_number = str(metadata.get("display_phone_number") or "").strip()
        messages: list[dict] = []
        for thread in _threads(value):
            thread_id = str(thread.get("id") or thread.get("wa_id") or "").strip()
            if not thread_id:
                continue
            for msg in thread.get("messages") or []:
                normalized = _normalize_thread_message(msg, thread_id, business_number)
                if normalized is not None:
                    messages.append(normalized)
        batches.append(
            {
                "phone_number_id": _phone_number_id(value),
                "request_id": _request_id(value),
                "phase": _int_or_none(value.get("phase")),
                "chunk_order": _int_or_none(value.get("chunk_order")),
                "progress": _int_or_none(value.get("progress")),
                "messages": messages,
            }
        )
    return batches


# ---------- contacts ----------


def _contact_record(item: dict) -> dict | None:
    contact = item.get("contact") if isinstance(item.get("contact"), dict) else item
    phone = str(
        contact.get("phone_number") or contact.get("wa_id") or contact.get("phone") or ""
    ).strip()
    if not phone:
        return None
    name = str(
        contact.get("full_name")
        or " ".join(
            part
            for part in (contact.get("first_name"), contact.get("last_name"))
            if isinstance(part, str) and part
        )
        or ""
    ).strip()
    action = str(item.get("action") or "add").strip().lower()
    return {
        "phone": phone,
        "name": name or None,
        "action": action if action in ("add", "update", "remove") else "add",
        "username": str(contact.get("username") or "").strip() or None,
        "user_id": str(contact.get("user_id") or "").strip() or None,
    }


def parse_state_sync_batches(payload: dict) -> list[dict]:
    """Normalized contact batches: add / update / remove, with the phone as the identity.

    Meta only syncs contacts that HAVE a WhatsApp number, so a record without one is not a contact
    we can reach and is skipped rather than stored as a nameless row.
    """
    batches: list[dict] = []
    for value in _changes(payload, "smb_app_state_sync"):
        raw_contacts: list = []
        for key in ("state_sync", "contacts", "contact"):
            container = value.get(key)
            if isinstance(container, list):
                raw_contacts.extend(c for c in container if isinstance(c, dict))
            elif isinstance(container, dict):
                raw_contacts.append(container)
        contacts = [c for c in (_contact_record(item) for item in raw_contacts) if c]
        batches.append(
            {
                "phone_number_id": _phone_number_id(value),
                "request_id": _request_id(value),
                "contacts": contacts,
            }
        )
    return batches


# ---------- message echoes ----------


def parse_message_echoes(payload: dict) -> list[dict]:
    """The merchant's own messages, typed in the WhatsApp Business app on the phone.

    Each echo is an OUTBOUND message from a human: the customer is the ``to`` side, and the text,
    caption, media or reply context travels exactly like a live message so the inbox can show it.
    """
    echoes: list[dict] = []
    for value in _changes(payload, "smb_message_echoes"):
        raw: list = []
        for key in ("message_echoes", "messages", "echoes"):
            container = value.get(key)
            if isinstance(container, list):
                raw.extend(m for m in container if isinstance(m, dict))
        for msg in raw:
            customer_ref = str(
                msg.get("to") or msg.get("recipient_id") or msg.get("customer_ref") or ""
            ).strip()
            if not customer_ref:
                continue
            body, media_url, media_type, content_type = extract_content(msg)
            echoes.append(
                {
                    "channel_message_id": str(msg.get("id") or "").strip() or None,
                    "customer_ref": customer_ref,
                    "occurred_at": occurred_at(msg.get("timestamp")),
                    "body": body,
                    "media_url": media_url,
                    "media_type": media_type,
                    "content_type": content_type,
                    "reply_to_message_id": reply_context(msg),
                    "source": "whatsapp_business_app",
                    "raw": msg,
                }
            )
    return echoes


# ---------- unsupported messages ----------


def parse_unsupported_notices(payload: dict) -> list[dict]:
    """Messages Meta could not hand over, with the reason when it gives one.

    On a coexistence number this is usually the first message a customer sends after the link, or
    one from a companion device Meta does not support. The message exists in the merchant's app and
    will never reach FIHRIST, so the shop has to be told instead of the channel looking broken.
    """
    notices: list[dict] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            for status in value.get("statuses", []) or []:
                if not isinstance(status, dict):
                    continue
                for error in status.get("errors", []) or []:
                    if not isinstance(error, dict) or error.get("code") != UNSUPPORTED_MESSAGE_CODE:
                        continue
                    notices.append(
                        {
                            "code": UNSUPPORTED_MESSAGE_CODE,
                            "title": str(error.get("title") or "")[:200] or None,
                            "details": str(
                                (error.get("error_data") or {}).get("details")
                                or error.get("message")
                                or ""
                            )[:500]
                            or None,
                            "channel_message_id": str(status.get("id") or "") or None,
                        }
                    )
    return notices
