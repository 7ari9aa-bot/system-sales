"""Receipt UUID: SHA-256 of the serialized receipt with an empty ``uuid``.

The authority's published procedure (Receipt Issuance FAQ, "How to generate receipt UUID"):
  1. build the receipt including ``previousUUID`` (and ``referenceUUID`` for returns),
  2. leave ``uuid`` empty,
  3. serialize + normalize and flatten every property into one line of text,
  4. SHA-256 it, 5. hex-encode the 32 bytes into 64 characters, 6. that is the UUID.

UNVERIFIED (read before relying on this): the exact "serialize + normalize" step is implemented
inside the authority's Integration Toolkit and is not published as text anywhere we could reach.
The canonical form below (walk the object in document order, emit the upper-cased property name
then its quoted value, recurse into arrays and objects) is an EDUCATED GUESS modelled on the
authority's e-invoice signing canonicalization. It is deterministic and unit-tested for
stability, but nobody has compared it with the authority's output. Until that is done a receipt
signed with this UUID may be rejected with a "UUID is not a valid hash of the content" error.

To close this gap, run the same receipt through the Toolkit (offline, no account needed) and
through ``compute_receipt_uuid``, then put the pairs in ``tests/test_eta_uuid_toolkit_vectors.py``.
When every vector matches, flip ``NORMALIZATION_VERIFIED`` to True. ``EtaClient`` refuses to
submit to production while it is False.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.einvoice.providers.eta.codes import MAX_DECIMAL_PLACES

NORMALIZATION_VERIFIED = False
"""Flip to True only when ``test_eta_uuid_toolkit_vectors`` passes against real Toolkit output."""


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Floats are never produced by our builder (money is Decimal -> str); guard anyway.
        return format(value, f".{MAX_DECIMAL_PLACES}f")
    return str(value)


def canonical_string(node: Any, key: str | None = None) -> str:
    """Flatten ``node`` into the one-line canonical text that is hashed."""
    parts: list[str] = []
    if isinstance(node, dict):
        for name, value in node.items():
            parts.append(canonical_string(value, name))
    elif isinstance(node, list):
        # Array elements repeat the *parent's* name, then their own content.
        for element in node:
            parts.append(canonical_string(element, key))
    else:
        return f'"{(key or "").upper()}""{_scalar(node)}"'
    body = "".join(parts)
    if key is None:
        return body
    return f'"{key.upper()}"{body}'


def compute_receipt_uuid(receipt: dict[str, Any]) -> str:
    """UUID (64 hex chars) of ``receipt`` (the dict that goes into ``receipts[]``)."""
    working = json.loads(json.dumps(receipt))  # deep copy; never mutate the caller's dict
    working["header"]["uuid"] = ""
    digest = hashlib.sha256(canonical_string(working).encode("utf-8")).hexdigest()
    return digest


def is_valid_uuid_shape(value: str) -> bool:
    """True for a 64-char lowercase hex string (the only shape the authority accepts)."""
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
