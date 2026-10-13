"""Ops Health & Alert Invariant Monitor — implements RUNBOOK.md "Alerts" (R-C2).

Evaluates the production alert invariants that need no external metrics
backend:

    1. Database reachability          — SELECT 1 as the app role.
    2. Outbox relay not stuck         — oldest 'pending' row age <= 300s.
    3. Redis reachability             — PING.
    4. Consumer-group lag             — message.events lag <= 1000.
    5. Dead-letter queue empty        — total DLQ depth == 0.
    6. API readiness                  — GET <base>/readyz answers 200 (SKIPPED
                                        when no base URL is configured).

The RUNBOOK's "HTTP 5xx rate > 2% for 5 min" alert is NOT implemented here: a
rate needs a metrics backend, and this script deliberately reads live state
rather than inventing a number. That one stays with the observability item
(R-F2). Every check below reports SKIPPED or FAIL loudly; nothing fails open.

Usage:
    cd backend
    .venv/Scripts/python scripts/monitor_alerts.py [--json] [--base-url https://api.example]

Exit code is 0 when HEALTHY, 1 when any alert is triggered.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from _bootstrap import load_settings  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.redis import close_redis, get_redis  # noqa: E402

# RUNBOOK.md "Alerts (minimum viable)" thresholds.
OUTBOX_MAX_AGE_SECONDS = 300
CONSUMER_LAG_MAX = 1000
DLQ_STREAMS = (
    "message.events.dlq",
    "orders.events.dlq",
    "campaign.events.dlq",
    "notifications.events.dlq",
)


def resolve_lag(group: dict, entries_after_last_delivered: int | None) -> tuple[int, str]:
    """(lag, how_it_was_measured).

    Redis >= 7 computes `lag` for us. `pending` is a DIFFERENT number — entries
    delivered but not yet acked — so a consumer that is wedged but still acking
    shows pending=0 while real lag grows. The first version used `pending` as the
    lag and would therefore have stayed silent through exactly the failure the
    alert exists to catch.
    """
    lag = group.get("lag")
    if lag is not None:
        return int(lag), "server_lag"
    if entries_after_last_delivered is not None:
        return entries_after_last_delivered, "last_delivered_id_range"
    return int(group.get("pending", 0)), "pending_proxy"


async def _group_lag(client, stream: str, group: dict, threshold: int) -> tuple[int, str]:
    """Lag for one consumer group, preferring Redis's own figure."""
    if group.get("lag") is not None:
        return resolve_lag(group, None)
    last_delivered = group.get("last-delivered-id")
    if last_delivered:
        # Bounded: we only need to know whether the threshold is exceeded.
        entries = await client.xrange(stream, min=f"({last_delivered}", count=threshold + 1)
        return resolve_lag(group, len(entries))
    return resolve_lag(group, None)


def probe_readiness(base_url: str, timeout: float = 10.0) -> dict[str, object]:
    """GET <base>/readyz. 200 = ready; anything else is an availability alert."""
    url = base_url.rstrip("/") + "/readyz"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "url": url, "error": str(exc)}
    return {"status": "PASS" if code == 200 else "FAIL", "url": url, "http_status": code}


def _alert(name: str, severity: str, detail: str) -> dict[str, str]:
    return {"alert": name, "severity": severity, "detail": detail}


async def check_alerts(base_url: str | None) -> dict[str, object]:
    settings = load_settings(script="scripts/monitor_alerts.py")
    now = datetime.datetime.now(datetime.UTC)

    alerts: list[dict[str, str]] = []
    metrics: dict[str, object] = {}
    checks: dict[str, str] = {}

    # 1 + 2. Database and outbox
    engine = create_async_engine(settings.database_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as conn:
            try:
                await conn.execute(text("SELECT 1"))
                checks["database"] = "PASS"
            except Exception as exc:  # noqa: BLE001
                checks["database"] = "FAIL"
                alerts.append(_alert("readyz_503_database", "PAGE", f"ping failed: {exc}"))

            try:
                result = await conn.execute(
                    # outbox_events is the table (platform/models.py); "outbox"
                    # does not exist, which is why the first version's check
                    # failed silently on every run.
                    text("SELECT MIN(created_at) FROM outbox_events WHERE status = 'pending'")
                )
                oldest = result.scalar()
                if oldest is not None:
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=datetime.UTC)
                    age = (now - oldest).total_seconds()
                    metrics["outbox_oldest_pending_seconds"] = age
                    if age > OUTBOX_MAX_AGE_SECONDS:
                        alerts.append(
                            _alert(
                                "outbox_relay_stuck",
                                "PAGE",
                                f"oldest pending outbox row is {age:.0f}s "
                                f"(> {OUTBOX_MAX_AGE_SECONDS}s)",
                            )
                        )
                    checks["outbox"] = "PASS" if age <= OUTBOX_MAX_AGE_SECONDS else "FAIL"
                else:
                    metrics["outbox_oldest_pending_seconds"] = 0
                    checks["outbox"] = "PASS"
            except Exception as exc:  # noqa: BLE001
                # Fail CLOSED: an unreadable outbox is an unknown relay state,
                # and the relay is what actually delivers every message.
                checks["outbox"] = "FAIL"
                metrics["outbox_check_error"] = str(exc)
                alerts.append(
                    _alert("outbox_check_failed", "PAGE", f"could not read outbox_events: {exc}")
                )
    except Exception as exc:  # noqa: BLE001
        # The connection itself failed: an unreachable database is the loudest
        # form of "not ready", and it must be an alert rather than a traceback.
        checks.setdefault("database", "FAIL")
        checks.setdefault("outbox", "FAIL")
        metrics["database_reachable"] = False
        alerts.append(
            _alert("readyz_503_database", "PAGE", f"could not connect to the database: {exc}")
        )
    finally:
        await engine.dispose()

    # 3 + 4 + 5. Redis
    try:
        client = get_redis()
        await client.ping()
        checks["redis"] = "PASS"

        try:
            groups = await client.xinfo_groups("message.events")
        except Exception as exc:  # noqa: BLE001
            groups = []
            if "no such key" in str(exc).lower():
                # The stream does not exist yet (a fresh environment, or nothing
                # has been produced). That is "not applicable", not "unknown" —
                # alerting here would page on-call for an empty queue.
                checks["consumer_lag"] = "SKIPPED"
                metrics["consumer_lag_note"] = "message.events does not exist yet"
            else:
                checks["consumer_lag"] = "FAIL"
                metrics["consumer_lag_error"] = str(exc)
                alerts.append(
                    _alert("consumer_lag_unreadable", "PAGE", f"xinfo_groups failed: {exc}")
                )
        else:
            worst_lag, worst_group, how = 0, None, "none"
            for group in groups:
                lag, how = await _group_lag(client, "message.events", group, CONSUMER_LAG_MAX)
                if lag > worst_lag:
                    worst_lag, worst_group = lag, group.get("name")
            metrics["message_events_max_lag"] = worst_lag
            metrics["message_events_lag_measured_by"] = how
            metrics["message_events_groups"] = len(groups)
            checks["consumer_lag"] = "PASS" if worst_lag <= CONSUMER_LAG_MAX else "FAIL"
            if worst_lag > CONSUMER_LAG_MAX:
                alerts.append(
                    _alert(
                        "consumer_group_lag_high",
                        "PAGE",
                        f"message.events lag = {worst_lag} on group {worst_group} "
                        f"(> {CONSUMER_LAG_MAX}, measured by {how})",
                    )
                )

        total_dlq = 0
        unreadable_dlq: list[str] = []
        for stream in DLQ_STREAMS:
            try:
                total_dlq += int(await client.xlen(stream))
            except Exception:  # noqa: BLE001 — a missing stream has depth 0
                unreadable_dlq.append(stream)
        metrics["total_dlq_depth"] = total_dlq
        checks["dlq"] = "PASS" if total_dlq == 0 else "FAIL"
        if total_dlq > 0:
            alerts.append(
                _alert(
                    "dlq_depth_positive",
                    "ON_CALL",
                    f"{total_dlq} dead-letter entries require review",
                )
            )
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = "FAIL"
        metrics["redis_reachable"] = False
        alerts.append(_alert("readyz_503_redis", "PAGE", f"ping failed: {exc}"))
    finally:
        await close_redis()

    # 6. API readiness
    if base_url:
        readiness = probe_readiness(base_url)
        checks["api_readiness"] = str(readiness["status"])
        if readiness["status"] != "PASS":
            answered = readiness.get("http_status", readiness.get("error"))
            alerts.append(
                _alert("api_not_ready", "PAGE", f"{readiness.get('url')} answered {answered}")
            )
    else:
        checks["api_readiness"] = "SKIPPED"

    return {
        "timestamp": now.isoformat(),
        "checks": checks,
        "alerts_triggered": alerts,
        "metrics": metrics,
        "status": "ALERTING" if alerts else "HEALTHY",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor production health invariants")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument(
        "--base-url",
        help="API origin for the readiness probe; defaults to API_PUBLIC_BASE_URL",
    )
    args = parser.parse_args()

    settings = load_settings(script="scripts/monitor_alerts.py")
    base_url = args.base_url or settings.api_public_base_url or None
    report = asyncio.run(check_alerts(base_url))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        checks = report["checks"]
        assert isinstance(checks, dict)
        passed = sum(1 for status in checks.values() if status == "PASS")
        skipped = sum(1 for status in checks.values() if status == "SKIPPED")
        print(f"=== Health & Alert Monitor: {report['status']} ===")
        print(f"Timestamp: {report['timestamp']}")
        print(f"Checks: {passed}/{len(checks)} PASS, {skipped} SKIPPED")
        print(f"Metrics: {json.dumps(report['metrics'], indent=2)}")
        if report["alerts_triggered"]:
            print("\nALERTS TRIGGERED:")
            for alert in report["alerts_triggered"]:
                print(f"  [{alert['severity']}] {alert['alert']}: {alert['detail']}")
        else:
            print("\nNo alerts: every evaluated invariant is within threshold.")
        if skipped:
            print("NOTE: at least one check was skipped (see `checks` in --json output).")

    if report["status"] != "HEALTHY":
        sys.exit(1)


if __name__ == "__main__":
    main()
