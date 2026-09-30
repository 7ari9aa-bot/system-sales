"""Referent resolver tests (spec §8) — pure logic, no database.

Pins the Arabic normalization (spoken hamza/alef variants must match), the
1-based shown-order semantics, the honest out-of-range and empty-list Nones,
and that bare "ده" means the current topic (the last shown item).
"""

from __future__ import annotations

from app.modules.ai.agents.customer.referents import (
    normalize_arabic,
    resolve_referent,
)

SHOWN = ["p-first", "p-second", "p-third"]


def test_second_points_at_the_second_shown_item():
    ref = resolve_referent("ابعت لي صورة التاني", SHOWN)
    assert ref is not None
    assert ref.product_id == "p-second"
    assert ref.position == 2


def test_spoken_alef_variants_normalize_to_the_same_marker():
    # الأول (hamza) and الاول (plain) are the same word to a customer.
    assert normalize_arabic("الأولاني") == normalize_arabic("الاولاني")
    ref = resolve_referent("وريني الأول", SHOWN)
    assert ref is not None and ref.product_id == "p-first"

    ref = resolve_referent("الأولاني", SHOWN)
    assert ref is not None and ref.position == 1


def test_third_and_diacritics():
    ref = resolve_referent("التَّالت", SHOWN)  # harakat must not break matching
    assert ref is not None and ref.product_id == "p-third"


def test_last_and_previous_and_deh_mean_the_current_topic():
    for utterance in ("الاخير", "اللي فات", "ده", "وريني دي"):
        ref = resolve_referent(utterance, SHOWN)
        assert ref is not None, utterance
        assert ref.product_id == "p-third"
        assert ref.position == 3


def test_out_of_range_ordinal_returns_none_not_a_guess():
    # Only three items were shown; "التالت" works, "الرابع" vocabulary does
    # not exist in v1 — and there is nothing at position 4 to return anyway.
    assert resolve_referent("التالت", SHOWN[:2]) is None


def test_no_marker_returns_none():
    assert resolve_referent("ابعت لي صورة", SHOWN) is None


def test_empty_shown_list_returns_none_even_for_a_clear_marker():
    assert resolve_referent("التاني", []) is None
