"""The server must outlive the screen that waits for it.

The settings screen waits 10 minutes for the Facebook window and then says it expired. The state
token that window returns with also lived exactly 10 minutes, and its clock starts BEFORE the
screen's (the screen starts waiting after the start request has answered). So an owner who finished
in the last seconds met `invalid_state` while the screen was still waiting for them.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.applications.apparel.modules.customers import meta_oauth as mo

# The connect flow moved out of the channels screen into its own module (ee7a730 / 055e94d), so
# the waits are armed in the hook and its helpers now, not in ChannelsSettings.jsx.
CHANNELS = Path(__file__).resolve().parents[2] / "frontend/src/pages/settings/channels"


def _screen_wait_seconds() -> list[int]:
    """Every `N * 60 * 1000` wait the connect flow arms for a connect window."""
    waits: list[int] = []
    for name in ("useChannelConnect.js", "channelHelpers.js"):
        waits += [
            int(m) * 60 for m in re.findall(r"(\d+) \* 60 \* 1000", (CHANNELS / name).read_text())
        ]
    return waits


def test_the_screen_still_waits_a_whole_number_of_minutes_we_can_read():
    assert _screen_wait_seconds(), "the screen's connect timers moved; update this guard"


def test_the_state_outlives_the_longest_wait_with_room_to_spare():
    longest = max(_screen_wait_seconds())
    assert mo._META_STATE_TTL_SECONDS >= longest + 120, (
        "an owner finishing on the screen's last second must still hold a valid state"
    )


def test_the_page_choice_ticket_outlives_the_screen_too():
    assert mo._PAGE_CHOICE_TTL_SECONDS >= max(_screen_wait_seconds()) + 120
