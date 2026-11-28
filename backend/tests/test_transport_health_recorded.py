"""A channel that still receives deliveries keeps its transport health current.

Only `active` channels used to be stamped, so one waiting to be reconnected (`reauth_required`) kept
looking as if nothing had ever arrived, and the "stopped" / "never arrived" signals were wrong for
exactly the channels that most need them.
"""

import uuid
from types import SimpleNamespace

from app.applications.apparel.modules.conversations.routers import webhooks as hooks


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Session:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.row)


def _row(health=None):
    return SimpleNamespace(webhook_health=health)


async def test_a_delivery_stamps_the_time_and_clears_the_failure_state():
    integration = _row({"consecutive_failures": 4, "last_error": "boom", "kept": 1})
    await hooks._record_transport_health(_Session(integration), uuid.uuid4(), "messenger")
    health = integration.webhook_health
    assert health["consecutive_failures"] == 0
    assert "last_error" not in health
    assert health["last_webhook_at"]
    assert health["kept"] == 1  # unrelated keys survive


async def test_a_channel_with_no_health_yet_gets_one():
    integration = _row(None)
    await hooks._record_transport_health(_Session(integration), uuid.uuid4(), "instagram")
    assert set(integration.webhook_health) == {"last_webhook_at", "consecutive_failures"}


async def test_no_matching_channel_is_a_quiet_no_op():
    session = _Session(None)
    await hooks._record_transport_health(session, uuid.uuid4(), "messenger")
    assert len(session.statements) == 1


def test_channels_waiting_to_reconnect_are_tracked_and_removed_ones_are_not():
    tracked = set(hooks.HEALTH_TRACKED_STATUSES)
    assert {"active", "connected", "reauth_required", "restricted"} <= tracked
    assert not tracked & {"disconnected", "disabled", "pending"}


async def test_the_query_asks_for_those_statuses_and_prefers_the_live_row():
    session = _Session(_row({}))
    await hooks._record_transport_health(session, uuid.uuid4(), "facebook")
    sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": False}))
    assert "integrations.status IN" in sql
    assert "ORDER BY CASE" in sql  # the live connection wins over a stale one
    assert "LIMIT" in sql  # two rows for one provider must not raise MultipleResultsFound
