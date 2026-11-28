"""Receipt UUID: SHA-256 of the serialized receipt with an empty ``uuid``.

The authority's published procedure (Receipt Issuance FAQ, "How to generate receipt UUID"):
  1. build the receipt including ``previousUUID`` (and ``referenceUUID`` for returns),
  2. leave ``uuid`` empty,
  3. serialize + normalize and flatten every property into one line of text,
  4. SHA-256 it, 5. hex-encode the 32 bytes into 64 characters, 6. that is the UUID.

VERIFIED AGAINST THE AUTHORITY'S OWN LIBRARY. Step 3 is not published as prose, but the authority
ships it as an MIT-licensed NuGet package, ``ETA.Ereceipt.UUID`` 1.0.0 (author "ETAEgypt"), whose
``Manager.GenerateUUID(json)`` does exactly: parse the JSON (numbers and dates kept as written),
then walk it depth first and emit, for every property, ``"`` + NAME UPPER-CASED + ``"`` followed by
its value; hash that text with SHA-256 over UTF-8 and write each byte as two lowercase hex digits.
The rules below were read from that library's IL and then checked against its real output (the
library was executed, no account needed): see ``tests/test_eta_uuid_toolkit_vectors.py``.

* a property whose value is text, a number, a date or a boolean: ``"NAME""value"``;
  numbers keep the exact text they were written with (``1.50000`` stays ``1.50000``) and booleans
  are written ``True`` / ``False`` (.NET's spelling);
* ``null`` and an empty object or array: the name alone, no value;
* an object: its name, then its properties in document order;
* an array of objects: its name, then for EACH element the name again followed by that element's
  properties. Arrays of plain values (numbers, strings) contribute only the repeated name; the
  authority's receipt has none, so we refuse them rather than guess.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

NORMALIZATION_VERIFIED = True
"""True because the rule above reproduces the authority's own library output (see the vectors)."""


class UnsupportedShape(ValueError):
    """The receipt holds a shape the authority's own serializer treats in a surprising way."""


_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def _escape(text: str) -> str:
    """Escape text the way Json.NET's ``JsonConvert.ToString`` does (the authority's library).

    Backslash, quote and the usual control letters get their short form, every other control
    character below U+0020 becomes ``\\u00xx`` (lowercase hex), and everything else, Arabic and
    emoji included, is written as is. Property NAMES are never escaped.
    """
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return _escape(str(value))


def canonical_string(node: Any, key: str | None = None) -> str:
    """Flatten ``node`` into the one-line canonical text that is hashed."""
    if isinstance(node, dict):
        body = "".join(canonical_string(v, k) for k, v in node.items())
        return body if key is None else f'"{key.upper()}"{body}'
    if isinstance(node, list):
        if key is None:
            raise UnsupportedShape("a receipt is an object, not an array")
        parts = [f'"{key.upper()}"']
        for element in node:
            if not isinstance(element, dict):
                raise UnsupportedShape(
                    f"array {key!r} holds a plain value; the authority's rule is not usable"
                )
            parts.append(canonical_string(element, key))
        return "".join(parts)
    if key is None:
        raise UnsupportedShape("a bare value has no property name")
    if node is None:
        return f'"{key.upper()}"'
    return f'"{key.upper()}""{_scalar(node)}"'


def compute_receipt_uuid(receipt: dict[str, Any]) -> str:
    """UUID (64 hex chars) of ``receipt`` (the dict that goes into ``receipts[]``)."""
    working = json.loads(json.dumps(receipt))  # deep copy; never mutate the caller's dict
    working["header"]["uuid"] = ""
    digest = hashlib.sha256(canonical_string(working).encode("utf-8")).hexdigest()
    return digest


def is_valid_uuid_shape(value: str) -> bool:
    """True for a 64-char lowercase hex string (the only shape the authority accepts)."""
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
