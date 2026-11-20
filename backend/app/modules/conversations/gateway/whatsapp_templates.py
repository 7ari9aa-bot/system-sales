"""WhatsApp message templates through the WhatsApp Business Management API.

A template only exists for Meta once it is created on the WhatsApp Business Account (WABA) and
reviewed there: the row in our own `message_templates` table is just a mirror of that. This
module is the one place that talks to Meta about templates; the lifecycle rules stay in
`conversations/templates.py`.

Limits enforced here BEFORE a request is spent (Meta rejects the rest with its own error, which
is surfaced as is):

* the name is lowercase letters, digits and underscores, at most 512 characters;
* the body is at most 1024 characters, a header text at most 60, a footer at most 60;
* variables are positional `{{1}}`, `{{2}}`... with no gap, and a body may not start or end
  with one (Meta refuses it);
* a template carries at most 10 buttons: up to 10 quick replies, 2 URL, 1 phone number.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_WHATSAPP, get_breaker
from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.gateway.base import parse_provider_body

GRAPH_BASE = "https://graph.facebook.com/v27.0"

#: What Meta calls a template's review state, mapped to ours. Anything not listed is left
#: alone: an unknown status must never silently make a template sendable.
META_STATUS_TO_OURS: dict[str, str] = {
    "APPROVED": "approved",
    "REJECTED": "rejected",
    "PENDING": "submitted",
    "IN_APPEAL": "submitted",
    "PAUSED": "paused",
    "DISABLED": "paused",
    "PENDING_DELETION": "archived",
    "DELETED": "archived",
}

CATEGORIES = frozenset({"UTILITY", "MARKETING", "AUTHENTICATION"})
BODY_MAX = 1024
HEADER_MAX = 60
FOOTER_MAX = 60
BUTTON_TEXT_MAX = 25
MAX_BUTTONS = 10
MAX_QUICK_REPLIES = 10
MAX_URL_BUTTONS = 2
MAX_PHONE_BUTTONS = 1

_NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def variables_in(text: str) -> list[int]:
    """The positional variable numbers a text uses, in order of appearance."""
    return [int(n) for n in _VAR_RE.findall(text or "")]


def check_positional(text: str, *, where: str) -> int:
    """How many variables `text` declares; raises when they skip a number or touch an edge."""
    found = variables_in(text)
    if not found:
        return 0
    expected = list(range(1, max(found) + 1))
    if sorted(set(found)) != expected:
        raise ValidationError(f"{where}: variables must be {{{{1}}}}, {{{{2}}}}... with no gap")
    if where == "body":
        stripped = (text or "").strip()
        # Meta refuses a body that opens or closes on a variable.
        if re.match(r"\{\{\s*\d+\s*\}\}", stripped) or re.search(r"\{\{\s*\d+\s*\}\}$", stripped):
            raise ValidationError("body may not start or end with a variable")
    return len(expected)


def build_components(
    *,
    body: str,
    header_text: str | None = None,
    footer: str | None = None,
    buttons: list[dict] | None = None,
    body_examples: list[str] | None = None,
    header_examples: list[str] | None = None,
) -> list[dict]:
    """The `components` array Meta wants, validated against its limits."""
    if not (body or "").strip():
        raise ValidationError("template body is required")
    if len(body) > BODY_MAX:
        raise ValidationError(f"body is at most {BODY_MAX} characters")
    count = check_positional(body, where="body")
    components: list[dict] = []

    if header_text:
        if len(header_text) > HEADER_MAX:
            raise ValidationError(f"header is at most {HEADER_MAX} characters")
        header_vars = check_positional(header_text, where="header")
        if header_vars > 1:
            raise ValidationError("a header may carry at most one variable")
        header: dict[str, Any] = {"type": "HEADER", "format": "TEXT", "text": header_text}
        if header_vars:
            if not header_examples:
                raise ValidationError("a header variable needs an example value")
            header["example"] = {"header_text": header_examples[:1]}
        components.append(header)

    body_component: dict[str, Any] = {"type": "BODY", "text": body}
    if count:
        if not body_examples or len(body_examples) < count:
            raise ValidationError(f"give {count} example value(s) for the body variables")
        body_component["example"] = {"body_text": [body_examples[:count]]}
    components.append(body_component)

    if footer:
        if len(footer) > FOOTER_MAX:
            raise ValidationError(f"footer is at most {FOOTER_MAX} characters")
        if variables_in(footer):
            raise ValidationError("a footer cannot carry variables")
        components.append({"type": "FOOTER", "text": footer})

    if buttons:
        components.append({"type": "BUTTONS", "buttons": _check_buttons(buttons)})
    return components


def _check_buttons(buttons: list[dict]) -> list[dict]:
    if len(buttons) > MAX_BUTTONS:
        raise ValidationError(f"a template has at most {MAX_BUTTONS} buttons")
    out: list[dict] = []
    kinds = {"QUICK_REPLY": 0, "URL": 0, "PHONE_NUMBER": 0}
    for button in buttons:
        kind = str(button.get("type") or "").upper()
        if kind not in kinds:
            raise ValidationError("a button is QUICK_REPLY, URL or PHONE_NUMBER")
        text = str(button.get("text") or "").strip()
        if not text or len(text) > BUTTON_TEXT_MAX:
            raise ValidationError(f"a button label is 1 to {BUTTON_TEXT_MAX} characters")
        kinds[kind] += 1
        item: dict[str, Any] = {"type": kind, "text": text}
        if kind == "URL":
            url = str(button.get("url") or "").strip()
            if not url.startswith("https://"):
                raise ValidationError("a URL button needs an https:// link")
            item["url"] = url
            if variables_in(url):
                if variables_in(url) != [1] or not url.endswith("{{1}}"):
                    raise ValidationError("a URL button may only end with {{1}}")
                item["example"] = [button.get("example") or url.replace("{{1}}", "example")]
        if kind == "PHONE_NUMBER":
            phone = str(button.get("phone_number") or "").strip()
            if not re.fullmatch(r"\+?[0-9]{7,15}", phone):
                raise ValidationError("a phone button needs digits, optionally starting with +")
            item["phone_number"] = phone
        out.append(item)
    if kinds["QUICK_REPLY"] > MAX_QUICK_REPLIES:
        raise ValidationError(f"at most {MAX_QUICK_REPLIES} quick replies")
    if kinds["URL"] > MAX_URL_BUTTONS:
        raise ValidationError(f"at most {MAX_URL_BUTTONS} URL buttons")
    if kinds["PHONE_NUMBER"] > MAX_PHONE_BUTTONS:
        raise ValidationError(f"at most {MAX_PHONE_BUTTONS} phone button")
    return out


HEADER_MEDIA_TYPES = frozenset({"image", "video", "document"})
BUTTON_PAYLOAD_MAX = 256
URL_PARAM_MAX = 2000


def _text_params(values: Any, *, where: str) -> list[dict]:
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        raise ValidationError(f"{where} must be a list")
    out = []
    for i, value in enumerate(values, start=1):
        text = str(value).strip() if value is not None else ""
        if not text:
            # Meta refuses an empty parameter with an opaque error: say which one.
            raise ValidationError(f"{where} #{i} is empty")
        out.append({"type": "text", "text": text})
    return out


def build_send_components(template_vars: dict | None) -> list[dict]:
    """The `components` of a template SEND, in the order Meta wants: header, body, buttons.

    Reads, from `template_vars`:

    * `header_params`: the header text variable (a list of one);
    * `header_media`: `{"type": "image|video|document", "link": "https://..."}` for a media header;
    * `body_params`: the body variables, in order;
    * `button_params`: `[{"index": 0, "type": "quick_reply", "payload": "..."},
      {"index": 1, "type": "url", "text": "suffix"}]`.

    Anything malformed is refused here, with a message naming the field: a half-built send would
    only come back from Meta as a generic error after the customer's window was already spent.
    """
    tv = template_vars or {}
    components: list[dict] = []

    header_media = tv.get("header_media")
    header_params = _text_params(tv.get("header_params"), where="header_params")
    if header_media and header_params:
        raise ValidationError("a header is either text or media, not both")
    if header_media:
        if not isinstance(header_media, dict):
            raise ValidationError("header_media must be an object")
        kind = str(header_media.get("type") or "").lower()
        link = str(header_media.get("link") or "").strip()
        if kind not in HEADER_MEDIA_TYPES:
            raise ValidationError("header_media.type must be image, video or document")
        if not link.startswith("https://"):
            raise ValidationError("header_media.link must be an https link")
        media: dict[str, Any] = {"link": link}
        if kind == "document" and header_media.get("filename"):
            media["filename"] = str(header_media["filename"])
        components.append({"type": "header", "parameters": [{"type": kind, kind: media}]})
    elif header_params:
        if len(header_params) != 1:
            raise ValidationError("a header takes exactly one variable")
        components.append({"type": "header", "parameters": header_params})

    body = _text_params(tv.get("body_params"), where="body_params")
    if body:
        components.append({"type": "body", "parameters": body})

    buttons = tv.get("button_params") or []
    if not isinstance(buttons, (list, tuple)):
        raise ValidationError("button_params must be a list")
    seen: set[int] = set()
    for raw in buttons:
        if not isinstance(raw, dict):
            raise ValidationError("every button_params entry must be an object")
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            raise ValidationError("a button needs a numeric index") from None
        if not 0 <= index < MAX_BUTTONS:
            raise ValidationError(f"button index must be 0 to {MAX_BUTTONS - 1}")
        if index in seen:
            raise ValidationError(f"button {index} is given twice")
        seen.add(index)
        kind = str(raw.get("type") or "").lower()
        if kind == "quick_reply":
            payload = str(raw.get("payload") or "").strip()
            if not payload:
                raise ValidationError(f"quick reply button {index} needs a payload")
            if len(payload) > BUTTON_PAYLOAD_MAX:
                raise ValidationError(f"button {index} payload is over {BUTTON_PAYLOAD_MAX}")
            param = {"type": "payload", "payload": payload}
        elif kind == "url":
            text = str(raw.get("text") or "").strip()
            if not text:
                raise ValidationError(f"url button {index} needs its variable text")
            if len(text) > URL_PARAM_MAX:
                raise ValidationError(f"button {index} text is over {URL_PARAM_MAX}")
            param = {"type": "text", "text": text}
        else:
            raise ValidationError("a button type is quick_reply or url")
        components.append(
            {"type": "button", "sub_type": kind, "index": str(index), "parameters": [param]}
        )
    # Meta reads buttons by position: send them in index order whatever order they came in.
    head = [c for c in components if c["type"] != "button"]
    tail = sorted((c for c in components if c["type"] == "button"), key=lambda c: int(c["index"]))
    return head + tail


def check_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not _NAME_RE.fullmatch(cleaned):
        raise ValidationError(
            "a WhatsApp template name uses lowercase letters, digits and underscores only"
        )
    return cleaned


def our_status(meta_status: str | None) -> str | None:
    """Our status for Meta's, or None when Meta's is not one we know how to map."""
    return META_STATUS_TO_OURS.get((meta_status or "").upper())


class WhatsAppTemplateClient:
    """Create, read and delete templates on one WABA."""

    def __init__(self, *, base: str = GRAPH_BASE):
        self._base = base

    @staticmethod
    def _token(credentials: dict) -> str:
        token = credentials.get("access_token")
        if not token:
            raise ExternalProviderError("whatsapp integration missing access_token")
        return str(token)

    @staticmethod
    def _waba(credentials: dict) -> str:
        waba = credentials.get("waba_id")
        if not waba:
            raise ExternalProviderError(
                "this WhatsApp channel has no business account id; reconnect it to manage templates"
            )
        return str(waba)

    async def _call(
        self,
        method: str,
        url: str,
        token: str,
        *,
        what: str,
        params: dict | None = None,
        json: dict | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"}

        async def _do() -> dict:
            if _client is not None:
                response = await _client.request(
                    method, url, headers=headers, params=params, json=json
                )
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.request(
                        method, url, headers=headers, params=params, json=json
                    )
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
        language: str,
        category: str,
        components: list[dict],
        _client: httpx.AsyncClient | None = None,
    ) -> dict:
        """Submit a template for review. Returns Meta's `{id, status, category}`."""
        category = (category or "").upper()
        if category not in CATEGORIES:
            raise ValidationError("category is UTILITY, MARKETING or AUTHENTICATION")
        data = await self._call(
            "POST",
            f"{self._base}/{self._waba(credentials)}/message_templates",
            self._token(credentials),
            what="template create",
            json={
                "name": check_name(name),
                "language": language,
                "category": category,
                "components": components,
            },
            _client=_client,
        )
        if not data.get("id"):
            raise ExternalProviderError(f"whatsapp template create: no id in {str(data)[:200]}")
        return data

    async def list(
        self,
        credentials: dict,
        *,
        name: str | None = None,
        limit: int = 100,
        _client: httpx.AsyncClient | None = None,
    ) -> list[dict]:
        """Every template on the WABA (all pages), each with its review status."""
        params: dict[str, Any] = {
            "limit": min(max(limit, 1), 100),
            "fields": "id,name,language,status,category,components,rejected_reason,quality_score",
        }
        if name:
            params["name"] = name
        url: str | None = f"{self._base}/{self._waba(credentials)}/message_templates"
        token = self._token(credentials)
        items: list[dict] = []
        for _ in range(20):  # a hard stop: no tenant has thousands of templates
            data = await self._call(
                "GET", url, token, what="template list", params=params, _client=_client
            )
            items.extend(i for i in (data.get("data") or []) if isinstance(i, dict))
            url = ((data.get("paging") or {}).get("next")) or None
            params = None  # the `next` link already carries them
            if not url:
                break
        return items

    async def delete(
        self,
        credentials: dict,
        *,
        name: str,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        """Delete every language of a template by name (Meta deletes by name)."""
        data = await self._call(
            "DELETE",
            f"{self._base}/{self._waba(credentials)}/message_templates",
            self._token(credentials),
            what="template delete",
            params={"name": check_name(name)},
            _client=_client,
        )
        if data.get("success") is not True:
            raise ExternalProviderError(f"whatsapp template delete refused: {str(data)[:200]}")


whatsapp_template_client = WhatsAppTemplateClient()
