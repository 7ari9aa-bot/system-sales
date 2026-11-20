"""WhatsApp interactive messages: reply buttons, lists and link buttons.

One entry point, `build_interactive(spec)`, turns a small, flat description into the exact
`interactive` object the Cloud API takes. Every limit below comes from Meta's own reference
(interactive reply buttons / list / call-to-action URL messages), and a spec that breaks one is
refused HERE, naming the field, before the customer waits on a rejection from Meta.

The three kinds do NOT share every limit, which is where hand-written code goes wrong:

    kind       body    header allowed          extra
    buttons    1024    text/image/video/doc    1-3 buttons, titles unique, title 20, id 256
    list       4096    text ONLY               1-10 sections, 10 rows in total, row id 200
    cta_url    1024    text/image/video/doc    one button, label 20, URL required

Lengths are counted in characters, as Meta counts them, not bytes: an Arabic label of 20
letters is 20, though it is 40 bytes.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.errors import ValidationError

KINDS = ("buttons", "list", "cta_url")

FOOTER_MAX = 60
HEADER_TEXT_MAX = 60

BUTTONS_BODY_MAX = 1024
BUTTONS_MAX = 3
BUTTON_TITLE_MAX = 20
BUTTON_ID_MAX = 256

LIST_BODY_MAX = 4096
LIST_BUTTON_MAX = 20
LIST_SECTIONS_MAX = 10
LIST_ROWS_MAX = 10  # across ALL sections together, not per section
LIST_SECTION_TITLE_MAX = 24
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESCRIPTION_MAX = 72
LIST_ROW_ID_MAX = 200

CTA_BODY_MAX = 1024
CTA_LABEL_MAX = 20
CTA_URL_MAX = 2000

HEADER_MEDIA_TYPES = ("image", "video", "document")


def _text(value, where: str, *, required: bool = False, limit: int) -> str | None:
    """A trimmed, length-checked string, or None when it is optional and empty."""
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise ValidationError(f"{where} must be text")
    if not text:
        if required:
            raise ValidationError(f"{where} is required")
        return None
    if len(text) > limit:
        raise ValidationError(f"{where} is at most {limit} characters (got {len(text)})")
    return text


def _https_url(value, where: str) -> str:
    """A public web address WhatsApp can open. Anything else is refused."""
    text = _text(value, where, required=True, limit=CTA_URL_MAX)
    assert text is not None
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError(f"{where} must be a full web address starting with https://")
    return text


def _header(spec: dict, *, text_only: bool) -> dict | None:
    header = spec.get("header")
    if header in (None, "", {}):
        return None
    if not isinstance(header, dict):
        raise ValidationError("header must be an object with a type")
    kind = header.get("type")
    if kind == "text":
        text = _text(header.get("text"), "header.text", required=True, limit=HEADER_TEXT_MAX)
        return {"type": "text", "text": text}
    if text_only:
        raise ValidationError("header of a list can only be text")
    if kind not in HEADER_MEDIA_TYPES:
        raise ValidationError("header.type must be text, image, video or document")
    link = _https_url(header.get("link"), "header.link")
    return {"type": kind, kind: {"link": link}}


def _common(spec: dict, *, body_max: int, text_only_header: bool) -> dict:
    body = _text(spec.get("body"), "body", required=True, limit=body_max)
    out: dict = {"body": {"text": body}}
    header = _header(spec, text_only=text_only_header)
    if header:
        out["header"] = header
    footer = _text(spec.get("footer"), "footer", limit=FOOTER_MAX)
    if footer:
        out["footer"] = {"text": footer}
    return out


def _buttons(spec: dict) -> dict:
    out = _common(spec, body_max=BUTTONS_BODY_MAX, text_only_header=False)
    raw = spec.get("buttons")
    if not isinstance(raw, list) or not raw:
        raise ValidationError("buttons: give 1 to 3 buttons")
    if len(raw) > BUTTONS_MAX:
        raise ValidationError(f"buttons: at most {BUTTONS_MAX} buttons (got {len(raw)})")
    seen_titles: set[str] = set()
    seen_ids: set[str] = set()
    built = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"buttons[{i}] must be an object with a title and id")
        title = _text(
            item.get("title"), f"buttons[{i}].title", required=True, limit=BUTTON_TITLE_MAX
        )
        button_id = _text(item.get("id"), f"buttons[{i}].id", required=True, limit=BUTTON_ID_MAX)
        assert title is not None and button_id is not None
        if title.casefold() in seen_titles:
            raise ValidationError(f"buttons[{i}].title repeats another button's title")
        if button_id in seen_ids:
            raise ValidationError(f"buttons[{i}].id repeats another button's id")
        seen_titles.add(title.casefold())
        seen_ids.add(button_id)
        built.append({"type": "reply", "reply": {"id": button_id, "title": title}})
    return {"type": "button", **out, "action": {"buttons": built}}


def _list(spec: dict) -> dict:
    out = _common(spec, body_max=LIST_BODY_MAX, text_only_header=True)
    label = _text(spec.get("button"), "button", required=True, limit=LIST_BUTTON_MAX)
    raw = spec.get("sections")
    if not isinstance(raw, list) or not raw:
        raise ValidationError("sections: give at least one section")
    if len(raw) > LIST_SECTIONS_MAX:
        raise ValidationError(f"sections: at most {LIST_SECTIONS_MAX} sections (got {len(raw)})")
    total = 0
    seen_ids: set[str] = set()
    sections = []
    for s, section in enumerate(raw):
        if not isinstance(section, dict):
            raise ValidationError(f"sections[{s}] must be an object")
        # Meta lists the section title as required, for a single section too.
        title = _text(
            section.get("title"),
            f"sections[{s}].title",
            required=True,
            limit=LIST_SECTION_TITLE_MAX,
        )
        rows_raw = section.get("rows")
        if not isinstance(rows_raw, list) or not rows_raw:
            raise ValidationError(f"sections[{s}].rows: give at least one row")
        rows = []
        for r, row in enumerate(rows_raw):
            where = f"sections[{s}].rows[{r}]"
            if not isinstance(row, dict):
                raise ValidationError(f"{where} must be an object with a title and id")
            total += 1
            if total > LIST_ROWS_MAX:
                raise ValidationError(
                    f"rows: at most {LIST_ROWS_MAX} rows in total across all sections"
                )
            row_id = _text(row.get("id"), f"{where}.id", required=True, limit=LIST_ROW_ID_MAX)
            assert row_id is not None
            if row_id in seen_ids:
                raise ValidationError(f"{where}.id repeats another row's id")
            seen_ids.add(row_id)
            built_row = {
                "id": row_id,
                "title": _text(
                    row.get("title"), f"{where}.title", required=True, limit=LIST_ROW_TITLE_MAX
                ),
            }
            description = _text(
                row.get("description"), f"{where}.description", limit=LIST_ROW_DESCRIPTION_MAX
            )
            if description:
                built_row["description"] = description
            rows.append(built_row)
        sections.append({"title": title, "rows": rows})
    return {"type": "list", **out, "action": {"button": label, "sections": sections}}


def _cta_url(spec: dict) -> dict:
    out = _common(spec, body_max=CTA_BODY_MAX, text_only_header=False)
    label = _text(spec.get("label"), "label", required=True, limit=CTA_LABEL_MAX)
    url = _https_url(spec.get("url"), "url")
    return {
        "type": "cta_url",
        **out,
        "action": {"name": "cta_url", "parameters": {"display_text": label, "url": url}},
    }


_BUILDERS = {"buttons": _buttons, "list": _list, "cta_url": _cta_url}


def build_interactive(spec: dict) -> dict:
    """The Cloud API `interactive` object for a flat description, or a ValidationError.

    Nothing is sent and nothing is stored here; this only checks and shapes.
    """
    if not isinstance(spec, dict):
        raise ValidationError("interactive must be an object")
    kind = spec.get("kind")
    if kind not in _BUILDERS:
        raise ValidationError(f"kind must be one of: {', '.join(KINDS)}")
    return _BUILDERS[kind](spec)


def preview_text(spec: dict) -> str:
    """What the thread should show for this message: the body, then each choice on its own line.

    The customer sees a bubble with buttons; the inbox keeps a plain, searchable text version so
    the conversation reads sensibly in lists, search and exports.
    """
    built = build_interactive(spec)
    lines = [built["body"]["text"]]
    action = built["action"]
    if built["type"] == "button":
        lines += [f"[ {b['reply']['title']} ]" for b in action["buttons"]]
    elif built["type"] == "list":
        lines.append(f"[ {action['button']} ]")
        for section in action["sections"]:
            lines += [f"- {row['title']}" for row in section["rows"]]
    else:
        lines.append(f"[ {action['parameters']['display_text']} ] {action['parameters']['url']}")
    return "\n".join(lines)
