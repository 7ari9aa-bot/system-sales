"""The structured half of a WhatsApp message: a place, a contact card, a tapped option.

The canonical row keeps a one-line body for every message, which is what a chat list needs. But a
shared location is not the text "📍 Café 12 Nile St": it has a latitude and a longitude that open a
map, and a shared contact is a name with phone numbers, not one concatenated string. The same goes
for a tapped list option, whose `id` is what a bot routes on — the title is for humans.

Nothing here reads or writes the database. Each function takes the stored webhook body and returns a
CHECKED dict, so only known fields ever reach a browser: a hostile or broken payload yields None
rather than being passed through.
"""

from __future__ import annotations

from typing import Any

#: Meta's own ceiling for a contact's phone list, and for the numbers in one card.
_MAX_PHONES = 5
_MAX_CONTACTS = 10


def _number(value: Any, *, limit: float) -> float | None:
    """A coordinate, as a number Meta would send, or None. Never a guess from a string label."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not -limit <= float(value) <= limit:
        return None
    return float(value)


def _text(value: Any, limit: int = 255) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def parse_location(raw: Any) -> dict | None:
    """A shared place: latitude/longitude plus the name and address the customer sent.

    Both coordinates are required by Meta, so a location without them is not a location and comes
    back None instead of a half-filled card that cannot open a map.
    """
    if not isinstance(raw, dict):
        return None
    location = raw.get("location") if isinstance(raw.get("location"), dict) else raw
    latitude = _number(location.get("latitude"), limit=90)
    longitude = _number(location.get("longitude"), limit=180)
    if latitude is None or longitude is None:
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "name": _text(location.get("name")),
        "address": _text(location.get("address"), limit=512),
    }


def parse_contacts(raw: Any) -> list[dict] | None:
    """Shared contact cards: a name and its phone numbers, at most a handful.

    A contact with no name and no number is nothing to show, so it is dropped rather than drawn as
    an empty card.
    """
    if not isinstance(raw, dict):
        return None
    contacts = raw.get("contacts")
    if not isinstance(contacts, list):
        return None
    out: list[dict] = []
    for entry in contacts[:_MAX_CONTACTS]:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") if isinstance(entry.get("name"), dict) else {}
        phones = [
            _text(phone.get("phone"), limit=32)
            for phone in (entry.get("phones") or [])[:_MAX_PHONES]
            if isinstance(phone, dict)
        ]
        card = {
            "name": _text(name.get("formatted_name")),
            "first_name": _text(name.get("first_name")),
            "last_name": _text(name.get("last_name")),
            "phones": [phone for phone in phones if phone],
        }
        if card["name"] or card["phones"]:
            out.append(card)
    return out or None


def parse_selection(raw: Any) -> dict | None:
    """A tapped reply button or list option: the id a bot routes on, plus the words shown.

    `id` is the important half. The canonical body keeps only the title, so without this a bot
    could not tell two options apart when the merchant reused a title across sections.
    """
    if not isinstance(raw, dict):
        return None
    interactive = raw.get("interactive") if isinstance(raw.get("interactive"), dict) else None
    if interactive is None:
        button = raw.get("button") if isinstance(raw.get("button"), dict) else None
        if button is None:
            return None
        # A template quick-reply carries text and a payload, no id.
        payload = _text(button.get("payload"), limit=255)
        return {"kind": "template_button", "id": payload, "title": _text(button.get("text"))}
    for kind, key in (("button", "button_reply"), ("list", "list_reply")):
        reply = interactive.get(key)
        if isinstance(reply, dict):
            return {
                "kind": kind,
                "id": _text(reply.get("id"), limit=255),
                "title": _text(reply.get("title")),
                "description": _text(reply.get("description"), limit=255),
            }
    return None


def structured_payload(content_type: str, raw: Any) -> dict | None:
    """The checked structured payload for a message kind, or None when it has none.

    Called at READ time from the stored webhook body, the same way the order card is rebuilt, so a
    row written before this existed still gets its map or its contact card.
    """
    if content_type == "location":
        location = parse_location(raw)
        return {"type": "location", **location} if location else None
    if content_type == "contact":
        contacts = parse_contacts(raw)
        return {"type": "contacts", "contacts": contacts} if contacts else None
    if content_type in ("buttons", "list"):
        selection = parse_selection(raw)
        return {"type": "selection", **selection} if selection else None
    return None
