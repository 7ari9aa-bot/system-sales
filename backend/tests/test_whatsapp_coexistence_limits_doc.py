"""The limits page must keep naming what coexistence does NOT sync.

Merchants read this page to decide whether linking costs them anything. A page that lists only the
good half invites a support ticket ("where are my groups?") and, worse, a sales promise Meta's API
cannot keep. The list below is the contract; the page is pinned to it.
"""

from __future__ import annotations

from pathlib import Path

PAGE = (
    Path(__file__).resolve().parents[2] / "docs" / "channels" / "whatsapp-coexistence-limits.md"
).read_text()

#: Every capability Meta's coexistence API does not carry into a partner system.
NOT_SYNCED = [
    "Groups",
    "Calls",
    "Status / stories",
    "Catalog, orders and shop tools",
    "Broadcast lists and labels",
    "unsupported companion devices",
    "WhatsApp for Windows",
    "WearOS",
    "131060",
    "6 months",
]


def test_the_page_lists_every_capability_that_is_not_synced() -> None:
    section = PAGE.split("## Not synced", 1)[1].split("## What the merchant", 1)[0]
    missing = [item for item in NOT_SYNCED if item not in section]
    assert not missing, f"the limits page stopped naming: {missing}"


def test_the_page_also_says_what_IS_synced() -> None:
    section = PAGE.split("## Synced", 1)[1].split("## Not synced", 1)[0]
    for item in ("smb_message_echoes", "smb_app_state_sync", "history", "PARTNER_REMOVED"):
        assert item in section, item


def test_the_page_is_indexed_so_it_can_be_found() -> None:
    index = (Path(__file__).resolve().parents[2] / "docs" / "README.md").read_text()
    assert "channels/whatsapp-coexistence-limits.md" in index
