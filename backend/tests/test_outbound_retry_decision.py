"""Which refused sends are tried again, and which never are.

The rule that matters most is negative: a send must never be repeated when it may already have
reached the customer, and a refusal that can never succeed must not be retried either.
"""

from __future__ import annotations

import pytest

from app.workers.outbound_retry import (
    RETRY_DELAYS_SECONDS,
    TRANSIENT_GRAPH_CODES,
    graph_error_code,
    is_transient_refusal,
    next_retry_delay,
)


def _refusal(code: int, status: int = 400) -> str:
    return f'whatsapp send failed: {status} {{"error": {{"message": "x", "code": {code}}}}}'


@pytest.mark.parametrize("code", sorted(TRANSIENT_GRAPH_CODES))
def test_every_documented_temporary_code_is_retried(code: int) -> None:
    assert is_transient_refusal(_refusal(code)) is True


@pytest.mark.parametrize(
    "code",
    [
        131047,  # re-engagement: the 24-hour window is closed, waiting never reopens it
        190,  # token expired or revoked
        10,  # permission denied
        200,  # permission denied
        131026,  # recipient cannot receive the message
        131030,  # recipient not in the allowed list
        131053,  # media upload failed
        368,  # account restricted
        100,  # invalid parameter
        0,
    ],
)
def test_a_refusal_that_can_never_succeed_is_not_retried(code: int) -> None:
    assert is_transient_refusal(_refusal(code)) is False


def test_the_table_holds_no_code_that_waiting_cannot_fix() -> None:
    assert not TRANSIENT_GRAPH_CODES & {131047, 190, 463, 467, 10, 200, 299, 131026, 131030}


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "connection reset by peer",
        "whatsapp send failed: 500 <html>Internal Server Error</html>",
        "messenger send failed: HTTP 429 - rate limit",  # prose, no Graph code
        "retry in 130429 seconds",  # a number in prose is not an error code
    ],
)
def test_text_without_a_graph_error_code_is_never_retried(text: str | None) -> None:
    assert graph_error_code(text) is None
    assert is_transient_refusal(text) is False


def test_two_different_codes_in_one_message_are_ambiguous_so_not_retried() -> None:
    both = '{"error": {"code": 4}} then {"error": {"code": 190}}'
    assert graph_error_code(both) is None
    assert is_transient_refusal(both) is False


def test_the_code_is_read_from_the_hash_form_graph_also_uses() -> None:
    assert graph_error_code("(#130429) Rate limit hit") == 130429
    assert is_transient_refusal("(#130429) Rate limit hit") is True


def test_a_code_nested_in_a_larger_body_is_found() -> None:
    body = 'messenger send failed: HTTP 400 - {"error": {"type": "OAuthException", "code": 613}}'
    assert graph_error_code(body) == 613


def test_the_budget_is_three_retries_then_final() -> None:
    assert [next_retry_delay(n) for n in (1, 2, 3)] == list(RETRY_DELAYS_SECONDS)
    assert next_retry_delay(4) is None
    assert next_retry_delay(99) is None


def test_no_attempt_yet_means_nothing_to_wait_for() -> None:
    assert next_retry_delay(0) is None
    assert next_retry_delay(-1) is None


def test_delays_grow() -> None:
    assert list(RETRY_DELAYS_SECONDS) == sorted(RETRY_DELAYS_SECONDS)
    assert len(set(RETRY_DELAYS_SECONDS)) == len(RETRY_DELAYS_SECONDS)
