"""Command hashing (V12 §22) — the deterministic binding between what was
approved and what may execute.

An Authority Lease (Wave B) stores a ``command_hash``; the execution request
must arrive with the SAME hash or nothing runs. That only means something if
the hash is built from a CANONICAL serialization: two dict literals that agree
key-by-key but spell their keys in a different order must produce one hash,
an amount of ``Decimal("950.00")`` and a float that merely prints ``950.0``
must never be confused, and an instant expressed in Cairo must equal the same
instant expressed in UTC.

Rules, each pinned by tests/test_command_hash.py:

- dict keys sort recursively; list order is semantic and preserved;
- separators are ``(",", ":")`` — no insignificant whitespace;
- ``ensure_ascii=False`` — Arabic text hashes as itself, not as \\u escapes;
- ``Decimal`` renders as its string form; ``float`` raises (float money poisons
  hashes — §47 keeps money out of binary floats, this file enforces it at the
  hashing boundary too);
- ``datetime`` normalizes to UTC and renders ``YYYY-MM-DDTHH:MM:SS.mmmZ``;
- anything JSON-irrelevant (sets, custom objects) is a hard error, not a guess.

The hash itself is ``sha256:<hex>`` over the canonical string, prefixed so a
log line or a lease row is self-describing about its scheme.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from decimal import Decimal
from typing import Any


class CanonicalJSONError(TypeError):
    """A value that has no deterministic JSON form reached canonical_json()."""


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        # Money travels as Decimal (§47); its string form is exact by
        # definition — Decimal("950.00") hashes differently from
        # Decimal("950.0"), deliberately: the scale was approved too.
        return str(value)
    if isinstance(value, float):
        raise CanonicalJSONError(
            "float has no deterministic canonical form; pass Decimal or str "
            f"for {value!r} (money must not cross this boundary as float)"
        )
    if isinstance(value, _dt.datetime):
        instant = value
        if instant.tzinfo is None:
            raise CanonicalJSONError(
                "naive datetime has no timezone to canonicalize; pass tz-aware"
            )
        instant = instant.astimezone(_dt.UTC)
        return instant.strftime("%Y-%m-%dT%H:%M:%S.") + f"{instant.microsecond // 1000:03d}Z"
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(k): _canonicalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    raise CanonicalJSONError(f"type {type(value).__name__} has no canonical JSON form: {value!r}")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` so equal logical commands produce equal strings."""
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def command_hash(
    tenant_id: str,
    action: str,
    resource: dict[str, Any],
    arguments: dict[str, Any],
    purpose: str,
) -> str:
    """The V12 §22 hash: sha256 over the canonical execution command.

    The payload shape is the spec's own — tenant, action, resource, arguments,
    purpose — nothing else. Any field the approval did not see must not be able
    to sneak into the hashed shape, so the signature is positional-by-name and
    closed.
    """
    payload = {
        "tenant_id": tenant_id,
        "action": action,
        "resource": resource,
        "arguments": arguments,
        "purpose": purpose,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
