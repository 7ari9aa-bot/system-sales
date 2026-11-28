"""A channel's health must be able to fail: stale and failing webhooks are visible."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.platform.routers.health import (
    WEBHOOK_FAILURES_DOWN,
    WEBHOOK_STALE_AFTER,
    integration_health,
    webhook_staleness,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


@pytest.mark.parametrize("health", [None, {}, {"consecutive_failures": 0}])
def test_a_channel_that_never_received_anything_is_not_failing(health):
    assert integration_health(health, now=NOW) == "healthy"


def test_recent_deliveries_are_healthy():
    assert integration_health({"last_webhook_at": _ago(minutes=5)}, now=NOW) == "healthy"


def test_a_channel_that_went_quiet_is_degraded():
    stale = _ago(seconds=int(WEBHOOK_STALE_AFTER.total_seconds()) + 60)
    assert integration_health({"last_webhook_at": stale}, now=NOW) == "degraded"


def test_just_inside_the_window_is_still_healthy():
    inside = _ago(seconds=int(WEBHOOK_STALE_AFTER.total_seconds()) - 60)
    assert integration_health({"last_webhook_at": inside}, now=NOW) == "healthy"


def test_failures_degrade_then_take_the_channel_down():
    assert integration_health({"consecutive_failures": 1}, now=NOW) == "degraded"
    assert integration_health({"consecutive_failures": WEBHOOK_FAILURES_DOWN}, now=NOW) == "down"


def test_failures_win_over_a_fresh_delivery():
    health = {"last_webhook_at": _ago(minutes=1), "consecutive_failures": WEBHOOK_FAILURES_DOWN}
    assert integration_health(health, now=NOW) == "down"


@pytest.mark.parametrize("raw", ["not a date", "", None, 12, {}])
def test_an_unreadable_timestamp_never_raises(raw):
    assert webhook_staleness({"last_webhook_at": raw}, now=NOW) is None
    assert integration_health({"last_webhook_at": raw}, now=NOW) == "healthy"


def test_a_naive_timestamp_is_read_as_utc():
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert webhook_staleness({"last_webhook_at": naive}, now=NOW) == timedelta(hours=1)


# --- the failure counter is actually written (it used to be written as 0 and nothing else) ---

import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.applications.apparel.modules.conversations.gateway.ingest import IngestService  # noqa: E402

FAKE_TOKEN = "fake-EAAUtSPZCPZCF0BT-fakefakefakefakefake1234567890"


class _Result:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar


class _Session:
    """UPDATE -> row lookup -> integration lookup, in the order the code issues them."""

    def __init__(self, integration, row):
        self.integration, self.row, self.calls = integration, row, 0

    async def execute(self, _statement):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(rowcount=1)
        if self.calls == 2:
            return _Result(first=self.row)
        return _Result(scalar=self.integration)


def _row():
    return SimpleNamespace(provider="messenger", tenant_id=uuid.uuid4(), processing_status="failed")


async def _fail(integration, row, exc, monkeypatch):
    seen = []

    async def fake(key, **kw):
        seen.append((key, kw))

    monkeypatch.setattr("app.core.meta_diagnostics.record_channel_issue", fake)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(worker_max_attempts=3)
    )
    await IngestService.mark_webhook_event_failed(_Session(integration, row), uuid.uuid4(), exc)
    return seen


async def test_a_failed_delivery_counts_on_the_channel(monkeypatch):
    integration = SimpleNamespace(webhook_health={"last_webhook_at": "2026-11-20T10:00:00+00:00"})
    seen = await _fail(integration, _row(), RuntimeError("boom"), monkeypatch)
    assert integration.webhook_health["consecutive_failures"] == 1
    assert integration.webhook_health["last_error"] == "boom"
    assert integration.webhook_health["last_failure_at"]
    assert integration.webhook_health["last_webhook_at"] == "2026-11-20T10:00:00+00:00"
    assert [k for k, _ in seen] == ["webhook.processing_failed"]


async def test_failures_accumulate_until_the_channel_is_down(monkeypatch):
    integration = SimpleNamespace(
        webhook_health={"consecutive_failures": WEBHOOK_FAILURES_DOWN - 1}
    )
    await _fail(integration, _row(), RuntimeError("boom"), monkeypatch)
    assert integration_health(integration.webhook_health) == "down"


async def test_a_token_in_the_error_text_is_not_stored_on_the_channel(monkeypatch):
    integration = SimpleNamespace(webhook_health={})
    await _fail(integration, _row(), RuntimeError(f"GET ?access_token={FAKE_TOKEN}"), monkeypatch)
    assert FAKE_TOKEN not in str(integration.webhook_health)


async def test_a_row_without_a_tenant_is_left_alone(monkeypatch):
    integration = SimpleNamespace(webhook_health={})
    row = SimpleNamespace(provider="messenger", tenant_id=None)
    seen = await _fail(integration, row, RuntimeError("boom"), monkeypatch)
    assert integration.webhook_health == {} and seen == []


async def test_bookkeeping_failure_never_breaks_the_quarantine(monkeypatch):
    class _Broken(_Session):
        async def execute(self, statement):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(rowcount=1)
            raise RuntimeError("database went away")

    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: SimpleNamespace(worker_max_attempts=3)
    )
    await IngestService.mark_webhook_event_failed(
        _Broken(None, None), uuid.uuid4(), RuntimeError("x")
    )


# ---- a linked channel that never hears from Meta ------------------------------------------
# "Never received anything" used to be healthy forever: right for a connection a minute old,
# wrong for one linked weeks ago whose webhook subscription silently never worked (app still in
# Development mode, a missing field, a wrong callback). That channel looks fine and is dead.

from app.modules.platform.routers.health import (  # noqa: E402
    NO_WEBHOOK_AFTER_LINK,
    integration_health_since_link,
)


def test_a_just_linked_channel_with_no_webhook_yet_is_still_healthy():
    assert integration_health_since_link({}, linked_at=_ago(minutes=5), now=NOW) == "healthy"


def test_a_channel_linked_long_ago_that_never_received_anything_is_degraded():
    linked = (NOW - NO_WEBHOOK_AFTER_LINK - timedelta(minutes=1)).isoformat()
    assert integration_health_since_link({}, linked_at=linked, now=NOW) == "degraded"


def test_the_first_webhook_ends_the_wait():
    health = {"last_webhook_at": _ago(minutes=3)}
    assert integration_health_since_link(health, linked_at=_ago(days=30), now=NOW) == "healthy"


@pytest.mark.parametrize("linked_at", [None, "", "not-a-date", 12345])
def test_an_unknown_link_time_never_raises_and_never_cries_wolf(linked_at):
    assert integration_health_since_link({}, linked_at=linked_at, now=NOW) == "healthy"


def test_failures_still_win_over_the_link_age():
    health = {"consecutive_failures": WEBHOOK_FAILURES_DOWN}
    assert integration_health_since_link(health, linked_at=_ago(days=30), now=NOW) == "down"


# ---- the roll-up must apply that rule only to channels that can be silent -----------------


async def _rollup(db, tenant_ctx, rows: list[dict]) -> dict:
    import uuid

    from app.modules.platform.models import Integration
    from app.modules.platform.routers.health import _integrations_subsystem

    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    for row in rows:
        db.add(
            Integration(
                id=uuid.uuid4(),
                tenant_id=tenant_ctx.tenant_id,
                kind=row.get("kind", "channel"),
                provider=row["provider"],
                status=row.get("status", "active"),
                config={"_connection": {"verified_at": old}},
                webhook_health=row.get("health", {}),
                credentials={},
            )
        )
    await db.flush()
    ctx = type("Ctx", (), {"session": db, "tenant_id": tenant_ctx.tenant_id})()
    return await _integrations_subsystem(ctx)


async def test_a_live_channel_linked_days_ago_that_never_heard_from_meta_is_degraded(
    db, tenant_ctx
):
    result = await _rollup(db, tenant_ctx, [{"provider": "messenger"}])
    assert result["integrations"] == [{"provider": "messenger", "status": "degraded"}]
    assert result["status"] == "degraded"


async def test_a_channel_that_is_receiving_stays_healthy(db, tenant_ctx):
    health = {"last_webhook_at": datetime.now(UTC).isoformat()}
    result = await _rollup(db, tenant_ctx, [{"provider": "whatsapp", "health": health}])
    assert result["status"] == "healthy"


@pytest.mark.parametrize(
    "row",
    [
        {"provider": "messenger", "status": "pending"},
        {"provider": "messenger", "status": "disconnected"},
        {"provider": "messenger", "status": "reauth_required"},
        {"provider": "webchat"},
        {"provider": "stripe", "kind": "payment"},
    ],
)
async def test_rows_that_have_no_webhook_to_wait_for_are_never_called_silent(db, tenant_ctx, row):
    result = await _rollup(db, tenant_ctx, [row])
    assert result["integrations"][0]["status"] == "healthy", row
