"""M19: Meta's account-restriction and quality events must reach the channel's status.

Until now only the template event was handled, so a banned or restricted WhatsApp account kept
showing as healthy while every send failed. The payload shapes below are the ones in Meta's
`account_update` and `phone_number_quality_update` webhook references.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.gateway import ingest as ingest_mod
from app.applications.apparel.modules.conversations.gateway.whatsapp import whatsapp_adapter as adapter
from app.modules.platform.diagnostics import channel_problems


def _envelope(field: str, value: dict, account: str = "WABA-1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": account, "time": 1, "changes": [{"field": field, "value": value}]}],
    }


RESTRICTION = _envelope(
    "account_update",
    {
        "event": "ACCOUNT_RESTRICTION",
        "restriction_info": [
            {"restriction_type": "RESTRICTED_ADD_PHONE_NUMBER_ACTION", "expiration": 9}
        ],
    },
)
BAN = _envelope(
    "account_update",
    {"event": "DISABLED_UPDATE", "ban_info": {"waba_ban_state": "SCHEDULE_FOR_DISABLE"}},
)
VIOLATION = _envelope(
    "account_update", {"event": "ACCOUNT_VIOLATION", "violation_info": {"violation_type": "SPAM"}}
)
LIMIT = _envelope(
    "phone_number_quality_update",
    {
        "display_phone_number": "15550783881",
        "event": "UPGRADE",
        "max_daily_conversations_per_business": "TIER_10K",
    },
)
PARTNER = _envelope("account_update", {"event": "PARTNER_ADDED"})


# ------------------------------------------------------------------ parsing


def test_a_restriction_names_its_restriction_type():
    assert adapter.parse_account_signals(RESTRICTION) == [
        {
            "kind": "restriction",
            "event": "ACCOUNT_RESTRICTION",
            "detail": "RESTRICTED_ADD_PHONE_NUMBER_ACTION",
        }
    ]


def test_a_ban_and_a_violation_are_restrictions_with_their_own_detail():
    assert adapter.parse_account_signals(BAN)[0]["detail"] == "SCHEDULE_FOR_DISABLE"
    assert adapter.parse_account_signals(VIOLATION)[0]["detail"] == "SPAM"


def test_a_limit_change_is_informational_and_uses_the_new_field():
    assert adapter.parse_account_signals(LIMIT) == [
        {"kind": "limit", "event": "UPGRADE", "limit": "TIER_10K"}
    ]


def test_account_news_that_does_not_limit_sending_is_ignored():
    assert adapter.parse_account_signals(PARTNER) == []


def test_malformed_values_never_raise_and_are_clipped():
    junk = _envelope("account_update", {"event": "ACCOUNT_RESTRICTION", "restriction_info": "x"})
    assert adapter.parse_account_signals(junk)[0]["detail"] == ""
    long = _envelope(
        "account_update",
        {"event": "ACCOUNT_VIOLATION", "violation_info": {"violation_type": "A\n" + "B" * 500}},
    )
    detail = adapter.parse_account_signals(long)[0]["detail"]
    assert len(detail) <= 60 and "\n" not in detail
    assert adapter.parse_account_signals({"entry": [None, 3, {"changes": [None]}]}) == []


# ------------------------------------------------------------------ routing


@pytest.mark.parametrize("payload", [RESTRICTION, BAN, VIOLATION, LIMIT])
def test_account_only_envelopes_are_placed_by_business_account(payload):
    assert adapter.resolve_template_account(payload) == "WABA-1"


def test_an_envelope_mixing_account_news_with_messages_keeps_normal_routing():
    mixed = {
        "entry": [
            {
                "id": "WABA-1",
                "changes": [
                    {"field": "account_update", "value": {"event": "ACCOUNT_RESTRICTION"}},
                    {"field": "messages", "value": {"metadata": {"phone_number_id": "P1"}}},
                ],
            }
        ]
    }
    assert adapter.resolve_template_account(mixed) is None


# ------------------------------------------------------------------ applying


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Session:
    def __init__(self, row, fail=False):
        self.row, self.fail, self.flushed = row, fail, 0

    async def execute(self, _stmt):
        if self.fail:
            raise RuntimeError("db down")
        return _Result(self.row)

    async def flush(self):
        self.flushed += 1


def _integration(status="active", health=None):
    return SimpleNamespace(status=status, webhook_health=health)


async def _apply(row, signals, fail=False):
    session = _Session(row, fail)
    await ingest_mod._apply_account_signals(session, uuid.uuid4(), "whatsapp", signals)
    return session


RESTRICT = [{"kind": "restriction", "event": "DISABLED_UPDATE", "detail": "X"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "connected"])
async def test_a_restriction_restricts_a_live_channel_and_records_why(status):
    row = _integration(status)
    session = await _apply(row, RESTRICT)
    assert row.status == "restricted"
    assert row.webhook_health["account_restriction"]["detail"] == "X"
    assert session.flushed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disconnected", "reauth_required", "disabled", "restricted"])
async def test_a_restriction_never_moves_a_channel_that_is_not_live(status):
    row = _integration(status)
    await _apply(row, RESTRICT)
    assert row.status == status
    assert row.webhook_health["account_restriction"]["event"] == "DISABLED_UPDATE"


@pytest.mark.asyncio
async def test_a_limit_change_is_noted_without_touching_status_or_failures():
    row = _integration("active", {"consecutive_failures": 0})
    await _apply(row, [{"kind": "limit", "event": "UPGRADE", "limit": "TIER_10K"}])
    assert row.status == "active"
    assert row.webhook_health["messaging_limit"]["limit"] == "TIER_10K"
    assert row.webhook_health["consecutive_failures"] == 0
    assert "account_restriction" not in row.webhook_health


@pytest.mark.asyncio
async def test_existing_health_facts_are_kept():
    row = _integration("active", {"last_webhook_at": "T", "consecutive_failures": 2})
    await _apply(row, RESTRICT)
    assert row.webhook_health["last_webhook_at"] == "T"
    assert row.webhook_health["consecutive_failures"] == 2


@pytest.mark.asyncio
async def test_no_integration_and_a_database_error_are_both_harmless():
    await _apply(None, RESTRICT)
    await _apply(_integration(), RESTRICT, fail=True)


# ------------------------------------------------------------------ reporting


def test_a_restricted_channel_is_reported_with_meta_s_reason():
    health = {"account_restriction": {"event": "DISABLED_UPDATE", "detail": "SCHEDULE_FOR_DISABLE"}}
    [problem] = channel_problems([("whatsapp", "restricted", health)])
    assert any("DISABLED_UPDATE SCHEDULE_FOR_DISABLE" in r for r in problem["reasons"])


def test_a_stale_restriction_note_on_an_active_channel_is_not_a_problem():
    health = {"account_restriction": {"event": "DISABLED_UPDATE", "detail": "X"}}
    assert channel_problems([("whatsapp", "active", health)]) == []
