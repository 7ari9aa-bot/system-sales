"""Platform monitors — the "see it before the customer does" layer.

Three monitors the research (Sentry/Datadog/AWS OPS04) puts FIRST, each
pinned by a test that seeds the failure and asserts the trip:

- ERROR SPIKE: ≥3 errors in a 15-min window at ≥10% of events.
- SILENCE: no page_view events for 30 min WHILE the site had traffic in
  24h — the outage nobody reports (Datadog's "below 1" trick).
- PROBES: configured URLs fetched on a schedule; a non-2xx IS the finding.

The trip-dedupe test pins the cooldown: one bad hour alerts once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import app.modules.conversations.models  # noqa: F401 — registers agent_runs' conversations FK
import app.modules.customers.models  # noqa: F401 — registers notifications' customers FK
from app.modules.notifications.models import Notification
from app.modules.platform.models import VisitorEvent
from app.modules.platform.services import monitors
from app.modules.platform.services.monitors import evaluate_monitors


async def _seed(db, *, event_type: str, path: str = "/", minutes_ago: int = 5, **extra) -> None:
    db.add(
        VisitorEvent(
            visitor_id=f"visitor-{minutes_ago}{abs(hash(path)) % 99999}",
            session_id=f"session-{minutes_ago}{abs(hash(path)) % 99999}",
            event_type=event_type,
            path=path,
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            **extra,
        )
    )
    await db.flush()


async def test_healthy_traffic_trips_nothing(db, tenant_ctx) -> None:
    """20 page views + 1 error (5%) in the window = a normal site."""
    for i in range(20):
        await _seed(
            db,
            event_type="error" if i == 0 else "page_view",
            path="/",
            minutes_ago=i + 1,
        )
    alerts = await evaluate_monitors(db)
    assert not [a for a in alerts if a.code == "visitor_error_spike"]


async def test_an_error_spike_trips_with_the_worst_path(db, tenant_ctx) -> None:
    for i in range(10):
        await _seed(db, event_type="page_view", path="/", minutes_ago=i + 1)
    for i in range(4):
        await _seed(db, event_type="error", path="/checkout", minutes_ago=i + 1)

    alerts = await evaluate_monitors(db)
    spike = next(a for a in alerts if a.code == "visitor_error_spike")
    assert spike.severity == "critical"
    assert "/checkout" in spike.detail


async def test_silence_trips_only_when_the_site_had_traffic(db, tenant_ctx) -> None:
    """The "below 1" trick: a dead tracker on a DEAD site is fine; a dead
    tracker on a site that HAD traffic 24h-ago-to-now is the outage nobody
    reports."""
    # No events at all in the last 24h → silence is EXPECTED, no alarm.
    alerts = await evaluate_monitors(db)
    assert not [a for a in alerts if a.code == "telemetry_silence"]

    # Old traffic (24h+ ago is outside the "had traffic" window, so seed
    # within it but older than the silence window).
    await _seed(db, event_type="page_view", path="/", minutes_ago=60)
    alerts = await evaluate_monitors(db)
    silence = next(a for a in alerts if a.code == "telemetry_silence")
    assert silence.severity == "critical"


async def test_trip_dedupe_alerts_once_per_fingerprint() -> None:
    """The cooldown: the same fingerprint trips once per window, but a NEW
    fingerprint (another path) still alerts inside another's cooldown."""

    class _FakeRedis:
        def __init__(self) -> None:
            self.seen: set[str] = set()

        async def set(self, key, value, nx=False, ex=None):  # noqa: ANN001
            if not nx or key in self.seen:
                return False
            self.seen.add(key)
            return True

    from app.modules.platform.services.monitors import Alert, trip_if_new

    redis = _FakeRedis()
    first = [
        Alert("critical", "visitor_error_spike", "a", "fp:/a"),
        Alert("critical", "visitor_error_spike", "a again", "fp:/a"),
        Alert("critical", "visitor_error_spike", "b", "fp:/b"),
    ]
    fresh = await trip_if_new(redis, first)
    assert [a.fingerprint for a in fresh] == ["fp:/a", "fp:/b"]

    second = [Alert("critical", "visitor_error_spike", "a", "fp:/a")]
    assert await trip_if_new(redis, second) == [], "the cooldown must suppress a repeat"


async def test_probes_report_failures_without_raising(monkeypatch) -> None:
    """A probe failure IS the finding — the run must record it, never raise."""
    import httpx

    class _FailingClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def get(self, url):
            if "down" in url:
                raise httpx.ConnectError("refused")
            return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    monkeypatch.setattr(
        type(monitors.get_settings()),
        "owner_probe_urls",
        property(lambda self: "https://ok.test/,https://down.test/"),
        raising=False,
    )

    results = await monitors.run_probes()
    assert len(results) == 2
    by_url = {r["url"]: r for r in results}
    assert by_url["https://ok.test/"]["ok"] is True
    assert by_url["https://down.test/"]["ok"] is False
    assert by_url["https://down.test/"]["detail"] == "ConnectError"


async def test_trip_pushes_one_email_per_alert_per_operator(db, tenant_ctx, monkeypatch):
    """The routing layer: a fresh trip emails each active platform admin once
    (idempotency keyed on fingerprint + hour + recipient), and a delivery
    failure for one operator never blocks the next."""
    import uuid

    from app.core.config import get_settings
    from app.modules.identity.models import User
    from app.modules.platform.services.monitors import Alert
    from app.workers.scheduler_worker import _push_operator_emails

    # Force the delivery gate open: the push returns silently when email
    # delivery is unconfigured (the production default in some envs).
    monkeypatch.setattr(
        type(get_settings()),
        "auth_email_delivery_configured",
        property(lambda self: True),
        raising=False,
    )

    admin = User(
        email=f"ops-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        full_name="Ops",
        is_platform_admin=True,
        is_active=True,
    )
    admin2 = User(
        email=f"ops2-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        full_name="Ops2",
        is_platform_admin=True,
        is_active=True,
    )
    db.add_all([admin, admin2])
    await db.flush()

    sent: list[tuple[str, str]] = []

    class _Sender:
        def __init__(self, *a, **k) -> None:
            pass

        async def send_receipt(self, *, delivery_id, recipient, subject, html, text):
            sent.append((recipient, subject))
            if recipient == admin2.email:
                raise RuntimeError("resend down for this one")

    monkeypatch.setattr("app.modules.identity.email_delivery.ResendEmailSender", _Sender)
    alerts = [Alert("critical", "visitor_error_spike", "boom", "fp:/checkout")]

    await _push_operator_emails(db, alerts)

    assert len(sent) == 2, "each operator gets their own send"
    assert sent[0][0] == admin.email and "visitor_error_spike" in sent[0][1]


async def test_tenant_monitor_ai_cap_near_notifies_owners(db, tenant_ctx) -> None:
    """The merchant's own feed: spend at 95% of the tenant cap lands a
    health notification in the OWNER's bell (via the console registry)."""
    from decimal import Decimal

    from app.modules.ai.models import Agent, BudgetPolicy
    from app.modules.ai.usage import record_usage
    from app.modules.platform.services.monitors import evaluate_tenant_monitors

    agent = Agent(
        tenant_id=tenant_ctx.tenant_id,
        kind="customer",
        name="Assistant",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    await record_usage(db, tenant_ctx.tenant_id, agent_id=agent.id, cost=Decimal("9.60"))
    db.add(
        BudgetPolicy(
            tenant_id=tenant_ctx.tenant_id,
            period="monthly",
            hard_cap=Decimal("10"),
            on_exceed="warn",
        )
    )
    await db.flush()

    alerts = await evaluate_tenant_monitors(db, tenant_ctx.tenant_id)
    near = next(a for a in alerts if a.code == "ai_cap_near")
    assert near.severity == "warning"

    from app.modules.notifications.service import NotificationService
    from app.workers.scheduler_worker import _tenant_owner_ids

    owner_ids = await _tenant_owner_ids(db, tenant_ctx.tenant_id)
    created = await NotificationService.record_monitor_alerts(
        db, tenant_ctx.tenant_id, owner_ids, [near.as_dict()]
    )
    assert created >= 1

    # The notification landed in the owner's bell, once (dedup_key per day).
    rows = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_ctx.tenant_id,
                    Notification.kind == "health",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any("ai_cap_near" in (row.title or "") for row in rows)
    before = len(rows)
    await NotificationService.record_monitor_alerts(
        db,
        tenant_ctx.tenant_id,
        owner_ids,
        [near.as_dict()],
    )
    rows_after = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_ctx.tenant_id,
                    Notification.kind == "health",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows_after) == before, "the same-day reminder must dedupe"


async def test_tenant_monitor_silent_under_budget(db, tenant_ctx) -> None:
    """A tenant far from its cap with clean ingress trips nothing."""
    from app.modules.platform.services.monitors import evaluate_tenant_monitors

    alerts = await evaluate_tenant_monitors(db, tenant_ctx.tenant_id)
    assert alerts == []
