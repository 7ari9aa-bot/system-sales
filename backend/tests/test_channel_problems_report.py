"""A channel that needs attention says so, in words, and a lost customer message is never silent.

`check_integrations` used to report `error: None` while the status said degraded. It also never
looked at `webhook_events`, so a message that arrived and was never turned into a message left every
dashboard green.
"""

from app.platform.platform.diagnostics import (
    CHANNEL_FAILURE_THRESHOLD,
    UNPROCESSED_EVENT_STATUSES,
    channel_problems,
)


def _problems(rows, unprocessed=None):
    return {p["provider"]: p for p in channel_problems(rows, unprocessed)}


def test_a_healthy_channel_is_not_listed():
    assert channel_problems([("messenger", "active", {"consecutive_failures": 0})]) == []
    assert channel_problems([("messenger", "active", None)]) == []
    assert channel_problems([]) == []


def test_a_channel_waiting_to_be_reconnected_is_listed_with_its_state():
    found = _problems([("facebook", "reauth_required", {})])
    assert found["facebook"]["reasons"] == ["حالة: reauth_required"]


def test_repeated_failures_are_listed_only_at_the_threshold():
    below = {"consecutive_failures": CHANNEL_FAILURE_THRESHOLD - 1}
    at = {"consecutive_failures": CHANNEL_FAILURE_THRESHOLD, "last_error": "boom"}
    assert channel_problems([("whatsapp", "active", below)]) == []
    listed = _problems([("whatsapp", "active", at)])["whatsapp"]
    assert listed["failures"] == CHANNEL_FAILURE_THRESHOLD
    assert listed["last_error"] == "boom"


def test_a_received_but_unprocessed_message_makes_an_otherwise_healthy_channel_a_problem():
    healthy = [("instagram", "active", {"consecutive_failures": 0})]
    assert channel_problems(healthy, {}) == []
    listed = _problems(healthy, {"instagram": 2})["instagram"]
    assert listed["unprocessed"] == 2
    assert "2" in listed["reasons"][0]


def test_unprocessed_events_of_one_channel_do_not_leak_to_another():
    rows = [("messenger", "active", {}), ("instagram", "active", {})]
    found = _problems(rows, {"instagram": 5})
    assert set(found) == {"instagram"}


def test_a_channel_with_several_problems_lists_every_reason():
    rows = [("whatsapp", "restricted", {"consecutive_failures": 4})]
    found = _problems(rows, {"whatsapp": 1})["whatsapp"]
    assert len(found["reasons"]) == 3


def test_garbage_health_never_raises():
    for health in (
        {"consecutive_failures": "many"},
        {"consecutive_failures": None},
        {"last_error": 5},
    ):
        channel_problems([("telegram", "active", health)])
    # a bool is an int in Python; it must not read as a failure count
    assert _problems([("telegram", "active", {"consecutive_failures": True})]) == {}
    big = {"consecutive_failures": True}
    assert channel_problems([("telegram", "active", big)]) == []


def test_a_long_provider_error_is_cut():
    health = {"consecutive_failures": 9, "last_error": "x" * 900}
    assert len(_problems([("whatsapp", "active", health)])["whatsapp"]["last_error"]) == 200


def test_both_unfinished_states_count_as_lost():
    assert set(UNPROCESSED_EVENT_STATUSES) == {"failed", "dead"}
