"""The server must outlive the screen that waits for it.

The settings screen waits 10 minutes for the Facebook window and then says it expired. The state
token that window returns with also lived exactly 10 minutes, and its clock starts BEFORE the
screen's (the screen starts waiting after the start request has answered). So an owner who finished
in the last seconds met `invalid_state` while the screen was still waiting for them.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.customers import meta_oauth as mo

SCREEN = Path(__file__).resolve().parents[2] / "frontend/src/pages/settings/ChannelsSettings.jsx"


def _screen_wait_seconds() -> list[int]:
    """Every `N * 60 * 1000` wait the settings screen arms for a connect window."""
    return [int(m) * 60 for m in re.findall(r"(\d+) \* 60 \* 1000", SCREEN.read_text())]


def test_the_screen_still_waits_a_whole_number_of_minutes_we_can_read():
    assert _screen_wait_seconds(), "the screen's connect timers moved; update this guard"


def test_the_state_outlives_the_longest_wait_with_room_to_spare():
    longest = max(_screen_wait_seconds())
    assert mo._META_STATE_TTL_SECONDS >= longest + 120, (
        "an owner finishing on the screen's last second must still hold a valid state"
    )


def test_the_page_choice_ticket_outlives_the_screen_too():
    assert mo._PAGE_CHOICE_TTL_SECONDS >= max(_screen_wait_seconds()) + 120
