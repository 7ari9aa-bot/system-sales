"""What the account calls a browser, before any database is involved.

`describe_device` is the only part of the sessions feature that is pure, so it is
the only part that can be pinned without Postgres. The labels matter more than
they look: this is the text a person reads while deciding which session to kill,
so "Chrome · Windows" beside a real IP is what makes the decision possible, and
an unrecognised string must say so instead of inventing a device.
"""

from __future__ import annotations

import pytest

from app.platform.identity.services.session import describe_device

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.70"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (CHROME_WINDOWS, "Chrome · Windows"),
        (SAFARI_IPHONE, "Safari · iPhone"),
        (FIREFOX_LINUX, "Firefox · Linux"),
        (CHROME_ANDROID, "Chrome · Android"),
    ],
)
def test_a_known_browser_is_named_with_its_platform(user_agent: str, expected: str) -> None:
    assert describe_device(user_agent) == expected


def test_edge_is_not_reported_as_the_chrome_it_embeds() -> None:
    """Edge advertises Chrome; the more specific token has to win."""
    assert describe_device(EDGE_WINDOWS) == "Edge · Windows"


def test_a_bare_apple_webview_is_safari_not_chrome() -> None:
    assert describe_device(SAFARI_IPHONE).startswith("Safari")


def test_the_desktop_shell_is_named_by_its_own_token() -> None:
    assert describe_device("Mozilla/5.0 FIHRIST-desktop/1.4.0 Tauri/2.1") == "FIHRIST desktop"


@pytest.mark.parametrize("user_agent", [None, "", "curl/8.4.0", "   "])
def test_an_unknown_client_is_admitted_not_guessed(user_agent: str | None) -> None:
    assert describe_device(user_agent) == "Unknown device"


def test_the_label_never_leaks_the_raw_string() -> None:
    """The UA is shown as its own field; the label is a summary, not a copy."""
    label = describe_device(CHROME_WINDOWS)
    assert "Mozilla" not in label
    assert len(label) <= 32
