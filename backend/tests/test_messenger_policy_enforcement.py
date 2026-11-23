"""Meta's messaging-policy enforcement on the Page, recorded instead of ignored.

The report's Messenger gap: "messaging policy enforcement events recorded as operational state
with owner notification". Nothing read `messaging_policy_enforcement`, so a Page Meta had warned
and then blocked still looked healthy in FIHRIST and the agent kept writing replies that could not
be delivered.

Two halves, tested separately:

* the parser turns Meta's field into plain data (both spellings Meta has used, nothing guessed);
* the ingest hook records it as operational state — a BLOCK restricts the channel, a WARN only
  records — and as one notification row that a redelivery does not duplicate.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.conversations.gateway.messenger import MessengerAdapter


def _payload(field: str, value: dict, *, entry_time: int = 1_760_000_000) -> dict:
    return {
        "object": "page",
        "entry": [{"id": "111", "time": entry_time, "changes": [{"field": field, "value": value}]}],
    }


def test_a_block_is_parsed_with_its_reason():
    adapter = MessengerAdapter()
    events = adapter.parse_policy_events(
        _payload(
            "messaging_policy_enforcement",
            {"policy_enforcement": {"action": "BLOCK", "reason": "spam", "expiration_time": 1}},
        )
    )
    assert events == [
        {
            "action": "BLOCK",
            "reason": "spam",
            "expires_at": 1,
            "at": 1_760_000_000,
            "page_id": "111",
        }
    ]


def test_the_unwrapped_value_and_the_other_field_name_are_accepted():
    """Meta has shipped both spellings; a warning must not vanish over a key name."""
    adapter = MessengerAdapter()
    events = adapter.parse_policy_events(
        _payload("policy_enforcement", {"action": "warn", "reason": "policy"})
    )
    assert events[0]["action"] == "WARN"
    assert events[0]["reason"] == "policy"


def test_an_event_without_an_action_is_ignored_not_guessed():
    adapter = MessengerAdapter()
    assert (
        adapter.parse_policy_events(_payload("messaging_policy_enforcement", {"reason": "x"})) == []
    )
    assert adapter.parse_policy_events(_payload("messaging_policy_enforcement", {})) == []


def test_an_unrelated_change_is_not_a_policy_event():
    adapter = MessengerAdapter()
    assert adapter.parse_policy_events(_payload("feed", {"action": "BLOCK"})) == []


# ── the ingest hook ─────────────────────────────────────────────────────────────────────────────


class _Integration:
    def __init__(self, status: str = "active"):
        self.id = uuid.uuid4()
        self.status = status
        self.webhook_health: dict = {}


class _FakeSession:
    """Enough of AsyncSession for `_apply_policy_events`: one Integration row, and flushes."""

    def __init__(self, integration):
        self.integration = integration
        self.flushes = 0

    async def execute(self, _statement):  # noqa: ANN001
        class _Result:
            def __init__(self, row):
                self._row = row

            def scalar_one_or_none(self):
                return self._row

        return _Result(self.integration)

    async def flush(self):
        self.flushes += 1


@pytest.fixture()
def recorded(monkeypatch):
    """Capture the notification rows the hook writes."""
    from app.modules.conversations import page_activity_service as activity
    from app.modules.conversations.gateway import ingest as ingest_mod

    rows: list[dict] = []

    async def _record(_session, _tenant, **kwargs):
        rows.append(kwargs)

    monkeypatch.setattr(activity.PageActivityService, "record", _record)
    return ingest_mod, rows


@pytest.mark.asyncio
async def test_a_block_restricts_the_channel_and_notifies_the_owner(recorded):
    ingest_mod, rows = recorded
    integration = _Integration("active")
    session = _FakeSession(integration)

    await ingest_mod._apply_policy_events(
        session,
        uuid.uuid4(),
        "messenger",
        [{"action": "BLOCK", "reason": "spam", "at": 1_760_000_000, "page_id": "111"}],
    )

    assert integration.status == "restricted"
    assert integration.webhook_health["messaging_policy"]["action"] == "BLOCK"
    assert integration.webhook_health["messaging_policy"]["reason"] == "spam"
    assert rows[0]["kind"] == "policy"
    assert "أوقفت" in rows[0]["summary"]


@pytest.mark.asyncio
async def test_a_warning_is_recorded_and_does_not_restrict_a_working_channel(recorded):
    ingest_mod, rows = recorded
    integration = _Integration("active")
    session = _FakeSession(integration)

    await ingest_mod._apply_policy_events(
        session,
        uuid.uuid4(),
        "messenger",
        [{"action": "WARN", "reason": "slow replies", "at": 1_760_000_000, "page_id": "111"}],
    )

    assert integration.status == "active"
    assert integration.webhook_health["messaging_policy"]["action"] == "WARN"
    assert "تحذير" in rows[0]["summary"]


@pytest.mark.asyncio
async def test_a_disconnected_channel_is_not_moved_back_or_forward(recorded):
    """Only reconnecting changes a disconnected channel; an event is not a reconnect."""
    ingest_mod, _rows = recorded
    integration = _Integration("disconnected")

    await ingest_mod._apply_policy_events(
        _FakeSession(integration),
        uuid.uuid4(),
        "messenger",
        [{"action": "BLOCK", "reason": "spam", "at": 1_760_000_000, "page_id": "111"}],
    )

    assert integration.status == "disconnected"


@pytest.mark.asyncio
async def test_a_redelivery_uses_the_same_dedup_key(recorded):
    """Meta retries for days; the owner must not be nagged once per delivery."""
    from app.modules.conversations.page_activity_service import _dedup_key

    first = _dedup_key("messenger", "policy", "111", _at(1_760_000_000))
    again = _dedup_key("messenger", "policy", "111", _at(1_760_000_000))
    assert first == again


def _at(seconds: int):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(seconds, tz=UTC)
