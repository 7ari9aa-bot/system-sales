"""W14: the setup guide must name every secret a Meta webhook needs, in both languages.

The WhatsApp webhook fails closed without WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN, and the
guide never named them, so an operator following it got a server that refused every WhatsApp
message with no hint why. This pins the guide to the code that reads the variables.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings

GUIDE = (Path(__file__).resolve().parents[2] / "docs" / "META_SETUP.md").read_text()

#: The settings each Meta webhook reads (gateway/messenger.py, instagram.py, whatsapp.py).
WEBHOOK_SECRETS = [
    "MESSENGER_APP_SECRET",
    "MESSENGER_VERIFY_TOKEN",
    "INSTAGRAM_APP_SECRET",
    "INSTAGRAM_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
]
WEBHOOK_PATHS = ["messenger", "facebook", "instagram", "whatsapp"]


def _halves() -> tuple[str, str]:
    """(Arabic half, English half): the guide repeats itself in both languages."""
    english_at = GUIDE.index("## 1.")  # the English half numbers its sections
    return GUIDE[:english_at], GUIDE[english_at:]


@pytest.mark.parametrize("name", WEBHOOK_SECRETS)
def test_every_webhook_secret_is_real_settings_field(name):
    assert name.lower() in Settings.model_fields, f"{name} is not a setting the server reads"


@pytest.mark.parametrize("name", WEBHOOK_SECRETS)
def test_both_halves_of_the_guide_name_the_secret(name):
    arabic, english = _halves()
    assert name in arabic, f"{name} is missing from the Arabic half"
    assert name in english, f"{name} is missing from the English half"


@pytest.mark.parametrize("channel", WEBHOOK_PATHS)
def test_both_halves_give_the_callback_url_for_every_channel(channel):
    arabic, english = _halves()
    url = f"/api/v1/webhooks/{channel}"
    assert url in arabic, f"{url} is missing from the Arabic half"
    assert url in english, f"{url} is missing from the English half"
