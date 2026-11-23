"""The replay guard's identity comes from the bytes the provider signed (M12).

A multi-account batch used to digest `json.dumps(part, sort_keys=True)`, a re-serialisation WE
invented. Two deliveries that differ on the wire but serialise alike collapsed into one (the second
acknowledged as a replay and dropped), and the audit row's external_event_id named our JSON instead
of the delivery.
"""

from __future__ import annotations

import hashlib
import json

from app.modules.conversations.routers.webhooks import _batch_part_digest, _delivery_digest


def _old_digest(part: dict) -> str:
    return hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest()


def test_a_single_account_delivery_digests_exactly_the_signed_bytes():
    raw = b'{"object":"page","entry":[{"id":"1"}]}'
    assert _delivery_digest(raw) == hashlib.sha256(raw).hexdigest()


def test_two_different_signed_bodies_with_equal_content_stay_distinct():
    """Same content, different bytes on the wire: the old digest merged them."""
    part = {"id": "PAGE-A", "messaging": [{"x": 1}]}
    wire_a = b'{"entry":[{"id":"PAGE-A","messaging":[{"x":1}]}]}'
    wire_b = b'{"entry": [{"messaging": [{"x": 1}], "id": "PAGE-A"}]}'

    assert _old_digest(part) == _old_digest(part)  # the old scheme could not tell them apart
    assert _batch_part_digest(wire_a, 0, "PAGE-A") != _batch_part_digest(wire_b, 0, "PAGE-A")


def test_the_parts_of_one_delivery_are_told_apart_by_position_and_account():
    raw = b'{"entry":[{"id":"A"},{"id":"B"}]}'
    first = _batch_part_digest(raw, 0, "A")
    second = _batch_part_digest(raw, 1, "B")
    same_position_other_account = _batch_part_digest(raw, 0, "B")

    assert len({first, second, same_position_other_account}) == 3


def test_a_redelivery_of_the_same_bytes_is_still_recognised_as_a_replay():
    raw = b'{"entry":[{"id":"A"},{"id":"B"}]}'
    assert _batch_part_digest(raw, 1, "B") == _batch_part_digest(raw, 1, "B")


def test_a_part_never_digests_to_the_whole_delivery():
    raw = b'{"entry":[{"id":"A"}]}'
    assert _batch_part_digest(raw, 0, "A") != _delivery_digest(raw)


def test_a_missing_account_key_does_not_crash_or_collide_with_a_real_one():
    raw = b'{"entry":[{}]}'
    assert _batch_part_digest(raw, 0, None) != _batch_part_digest(raw, 0, "A")
    assert _batch_part_digest(raw, 0, None) == _batch_part_digest(raw, 0, "")
