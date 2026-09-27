"""V12 §22: the command hash binds what was approved to what may execute.

Every property here is a security property, not style: key-order independence,
Unicode stability, Decimal money, the float refusal, and the timezone
normalization. A regression in any of them means an approval silently covers
a different command than the one that runs.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.commands import CanonicalJSONError, canonical_json, command_hash

V12_EXAMPLE = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "action": "capture_payment",
    "resource": {"type": "order", "id": "84721"},
    "arguments": {"amount": Decimal("950"), "currency": "EGP"},
    "purpose": "checkout",
}


def test_the_v12_example_hash_is_stable_across_key_order():
    a = command_hash(**V12_EXAMPLE)
    reordered = {
        "purpose": V12_EXAMPLE["purpose"],
        "arguments": {"currency": "EGP", "amount": Decimal("950")},
        "resource": {"id": "84721", "type": "order"},
        "action": V12_EXAMPLE["action"],
        "tenant_id": V12_EXAMPLE["tenant_id"],
    }
    b = command_hash(**reordered)

    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_deeply_nested_key_order_does_not_change_the_hash():
    lines_a = {"lines": [{"sku": "B", "qty": 1}, {"sku": "A", "qty": 2}]}
    lines_b = {"lines": [{"qty": 1, "sku": "B"}, {"qty": 2, "sku": "A"}]}
    first = command_hash("t-1", "create_order", {"type": "order"}, lines_a, "checkout")
    second = command_hash("t-1", "create_order", {"type": "order"}, lines_b, "checkout")

    assert first == second


def test_list_order_is_semantic_and_survives():
    with_lines = canonical_json({"lines": ["a", "b"]})
    swapped = canonical_json({"lines": ["b", "a"]})

    assert with_lines != swapped


def test_arabic_hashes_as_itself_not_as_escapes():
    text = canonical_json({"claim": "الكمية ٣ متاحة"})

    assert "الكمية" in text
    assert "\\u" not in text


def test_decimal_money_keeps_its_scale_in_the_hash():
    as_exact = canonical_json({"amount": Decimal("950.00")})
    trimmed = canonical_json({"amount": Decimal("950.0")})

    assert as_exact != trimmed, "the approved scale is part of the command"


def test_float_money_is_refused_at_the_boundary():
    with pytest.raises(CanonicalJSONError, match="float"):
        canonical_json({"amount": 950.0})


def test_the_same_instant_in_two_timezones_hashes_equal():
    cairo = dt.datetime(2026, 9, 27, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    utc = dt.datetime(2026, 9, 27, 10, 0, 0, tzinfo=dt.UTC)

    assert canonical_json({"at": cairo}) == canonical_json({"at": utc})
    assert canonical_json({"at": utc}) == '{"at":"2026-09-27T10:00:00.000Z"}'


def test_a_naive_datetime_is_rejected_not_guessed():
    with pytest.raises(CanonicalJSONError, match="tz"):
        canonical_json({"at": dt.datetime(2026, 9, 27, 12, 0, 0)})


def test_non_json_types_fail_loudly():
    with pytest.raises(CanonicalJSONError):
        canonical_json({"payload": {1, 2, 3}})


def test_changing_one_approved_argument_changes_the_hash():
    approved = command_hash(**V12_EXAMPLE)
    mutated = command_hash(
        **{**V12_EXAMPLE, "arguments": {"amount": Decimal("9500"), "currency": "EGP"}}
    )

    assert approved != mutated, "950 approved must never authorize 9500 (V12 §22)"
