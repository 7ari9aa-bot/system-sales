"""The coexistence guide must describe the READY condition the code actually computes.

The guide said READY arrives when history completes or is refused, while ``channel_sync_state``
also waits for the contacts half to settle. A worker or a screen written from the guide would have
called a channel ready while Meta was still sending contacts. This pins the prose to the code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.applications.apparel.modules.conversations import whatsapp_sync as sync
from app.applications.apparel.modules.conversations.models import WhatsAppSyncRun

GUIDE = (
    Path(__file__).resolve().parents[2] / "docs" / "channels" / "whatsapp-coexistence.md"
).read_text()
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _run(**overrides) -> WhatsAppSyncRun:
    fields = {
        "phone_number_id": "456",
        "sync_type": "history",
        "onboarding_epoch": "2026-11-24T00:00:00+00:00",
        "state": "pending",
    }
    fields.update(overrides)
    return WhatsAppSyncRun(**fields)


def test_the_guide_names_both_halves_as_the_ready_condition() -> None:
    section = GUIDE.split("`READY` requires", 1)[1].split("* Progress arrives", 1)[0]
    assert "both** halves settled" in section
    assert "contacts" in section
    assert "history" in section
    # The deadline is described as settlement, never as a complete contact list.
    assert "settled_by" in section
    assert "never as a\n    complete list" in section


def test_the_code_agrees_with_what_the_guide_says() -> None:
    contacts_open = _run(
        sync_type="contacts", state="in_progress", deadline_at=NOW + timedelta(hours=1)
    )
    history_done = _run(state="completed")
    assert sync.channel_sync_state(contacts_open, history_done, now=NOW) != sync.STATE_READY

    contacts_settled = _run(
        sync_type="contacts", state="in_progress", deadline_at=NOW - timedelta(minutes=1)
    )
    assert sync.channel_sync_state(contacts_settled, history_done, now=NOW) == sync.STATE_READY

    history_refused = _run(state="not_shared")
    assert sync.channel_sync_state(contacts_settled, history_refused, now=NOW) == (
        sync.STATE_HISTORY_NOT_SHARED
    )
    assert sync.is_ready(sync.channel_sync_state(contacts_settled, history_refused, now=NOW))
