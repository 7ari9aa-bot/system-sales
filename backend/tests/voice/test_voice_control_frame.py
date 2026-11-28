"""The browser's one control on the audio socket.

Barge-in needs a way to say "the caller talked over you" on a socket that
otherwise carries only PCM. Before this, the receive loop read ``bytes`` and
ignored everything else, so a client had no way to interrupt at all: the loop's
mute existed and nothing could reach it.
"""

from __future__ import annotations

import pytest

from app.platform.voice.routers.sessions import control_frame


def test_an_interrupt_frame_is_recognised() -> None:
    assert control_frame('{"type": "interrupt"}') == "interrupt"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '"interrupt"',
        '{"type": "stop"}',
        '{"type": ""}',
        '{"action": "interrupt"}',
        "{}",
    ],
)
def test_everything_else_is_ignored_rather_than_guessed(text: str) -> None:
    assert control_frame(text) is None
