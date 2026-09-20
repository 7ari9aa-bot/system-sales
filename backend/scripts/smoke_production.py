"""End-to-end smoke against a LIVE deployment (review N-05).

The audit's complaint was that nothing proved the new surfaces work outside the
test suite: every new table was empty in production and the tests run against a
rolled-back transaction, so "it passed CI" and "it works" were the same claim.
This script closes that gap by actually driving the deployed API.

It registers a THROWAWAY tenant, exercises the new surfaces against it, and
prints a pass/fail table. It never touches an existing tenant.

    python scripts/smoke_production.py [--base-url URL] [--keep]

Cleanup: the throwaway tenant is deleted afterwards via the admin connection
(--keep leaves it in place for inspection). Requires DATABASE_URL_ADMIN for the
cleanup step only; everything else goes through the public API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

DEFAULT_BASE_URL = "https://api-production-81629.up.railway.app"

PASSWORD = "smoke-test-password-1"

_results: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


class Client:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.token: str | None = None

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        expect: tuple[int, ...] = (200,),
        raw: bool = False,
    ):
        url = f"{self.base}{path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as res:
                status, payload = res.status, res.read().decode()
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read().decode()
        except Exception as exc:  # noqa: BLE001
            return -1, {"error": str(exc)}

        ok = status in expect
        try:
            parsed = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            parsed = payload
        if raw:
            return status, parsed
        return (status if ok else -1), parsed


async def _admin_cleanup(slug: str, email: str) -> str:
    """Delete the throwaway tenant (cascades to its rows) and its owner user."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import get_settings

        url = get_settings().database_url_admin or get_settings().database_url_app_admin
        if not url:
            return (
                "skipped: no admin database URL configured. Delete manually with: "
                f"DELETE FROM tenants WHERE slug = '{slug}'; "
                f"DELETE FROM users WHERE email = '{email}';"
            )

        engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
        async with engine.begin() as conn:
            tenant = (
                await conn.execute(
                    text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug}
                )
            ).scalar_one_or_none()
            if tenant is None:
                return "nothing to delete"
            await conn.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant)}
            )
            await conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
        await engine.dispose()
        return "deleted"
    except Exception as exc:  # noqa: BLE001
        return f"cleanup failed: {exc}"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--keep", action="store_true", help="do not delete the smoke tenant")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    slug = f"smoke-{stamp}"
    email = f"smoke-{stamp}@salesos-demo.com"

    c = Client(args.base_url)
    print(f"smoke tenant: {slug} / {email}")
    print(f"target: {args.base_url}")
    print()

    # ---------------------------------------------------------- auth ------
    print("== auth ==")
    status, reg = c.call(
        "POST",
        "/api/v1/auth/register",
        {
            "email": email,
            "password": PASSWORD,
            "tenant_name": "Smoke Tenant",
            "tenant_slug": slug,
        },
        expect=(200, 201),
    )
    _record("POST /auth/register", status != -1, f"status={status}")

    status, tokens = c.call(
        "POST", "/api/v1/auth/login", {"email": email, "password": PASSWORD}
    )
    ok = status != -1 and isinstance(tokens, dict) and tokens.get("access_token")
    _record("POST /auth/login", bool(ok), f"status={status}")
    if not ok:
        print("\ncannot continue without a token")
        return 1
    c.token = tokens["access_token"]

    status, me = c.call("GET", "/api/v1/auth/me")
    _record("GET /auth/me", status != -1 and bool(me), f"status={status}")

    # ------------------------------------------- provisioning defaults ----
    print()
    print("== provisioning seed (N-05 / the bootstrap) ==")
    status, sub = c.call("GET", "/api/v1/billing/subscription")
    _record(
        "GET /billing/subscription (seeded trial)",
        status != -1 and isinstance(sub, dict) and sub.get("status") not in (None, "none"),
        f"status={status} body={json.dumps(sub)[:120] if sub else None}",
    )

    status, policies = c.call("GET", "/api/v1/sla/policies")
    rows = policies if isinstance(policies, list) else (policies or {}).get("items", [])
    _record(
        "GET /sla/policies (default seeded)",
        status != -1 and len(rows) >= 1,
        f"status={status} count={len(rows) if rows else 0}",
    )

    status, calendars = c.call("GET", "/api/v1/sla/calendars")
    rows = calendars if isinstance(calendars, list) else (calendars or {}).get("items", [])
    _record(
        "GET /sla/calendars (default seeded)",
        status != -1 and len(rows) >= 1,
        f"status={status} count={len(rows) if rows else 0}",
    )

    # ------------------------------------------------------ platform ------
    print()
    print("== platform ==")
    status, health = c.call("GET", "/api/v1/platform/health")
    health_status = health.get("status") if isinstance(health, dict) else None
    _record(
        "GET /platform/health",
        status != -1 and isinstance(health, dict),
        f"status={status} health={health_status}",
    )

    status, metrics = c.call("GET", "/api/v1/platform/metrics")
    _record(
        "GET /platform/metrics",
        status != -1 and isinstance(metrics, (list, dict)),
        f"status={status}",
    )

    status, flags = c.call("GET", "/api/v1/platform/flags")
    _record(
        "GET /platform/flags",
        status != -1,
        f"status={status}",
    )

    status, views = c.call("GET", "/api/v1/platform/saved-views")
    _record("GET /platform/saved-views", status != -1, f"status={status}")

    # -------------------------------------------------- notifications -----
    print()
    print("== notifications ==")
    status, summary = c.call("GET", "/api/v1/notifications/summary")
    _record(
        "GET /notifications/summary",
        status != -1 and isinstance(summary, dict) and "unread" in summary,
        f"status={status} body={json.dumps(summary)[:100] if summary else None}",
    )

    status, notifs = c.call("GET", "/api/v1/notifications")
    _record(
        "GET /notifications",
        status != -1 and isinstance(notifs, list),
        f"status={status} count={len(notifs) if isinstance(notifs, list) else '?'}",
    )

    status, unread = c.call("GET", "/api/v1/notifications/unread-count")
    _record("GET /notifications/unread-count", status != -1, f"status={status}")

    status, marked = c.call("POST", "/api/v1/notifications/mark-read", {"ids": [str(uuid.uuid4())]})
    _record(
        "POST /notifications/mark-read",
        status != -1 and isinstance(marked, dict) and "marked" in marked,
        f"status={status} body={marked}",
    )

    status, marked_all = c.call("POST", "/api/v1/notifications/mark-all-read")
    _record("POST /notifications/mark-all-read", status != -1, f"status={status}")

    # --------------------------------------------------------- tasks ------
    print()
    print("== tasks ==")
    status, created = c.call(
        "POST",
        "/api/v1/tasks",
        {"title": "Smoke task", "description": "created by the smoke script", "priority": 2},
        expect=(200, 201),
    )
    task_id = created.get("id") if isinstance(created, dict) else None
    _record("POST /tasks", status != -1 and bool(task_id), f"status={status}")

    status, tasks = c.call("GET", "/api/v1/tasks")
    _record(
        "GET /tasks",
        status != -1 and isinstance(tasks, list) and len(tasks) >= 1,
        f"status={status} count={len(tasks) if isinstance(tasks, list) else '?'}",
    )

    if task_id:
        status, updated = c.call(
            "POST", f"/api/v1/tasks/{task_id}/status", {"status": "in_progress"}
        )
        _record("POST /tasks/{id}/status", status != -1, f"status={status}")

        status, by_customer = c.call("GET", f"/api/v1/tasks?customer_id={uuid.uuid4()}")
        _record(
            "GET /tasks?customer_id= (the N-02 filter)",
            status != -1 and isinstance(by_customer, list),
            f"status={status} count={len(by_customer) if isinstance(by_customer, list) else '?'}",
        )

    # ----------------------------------------------------- customers ------
    print()
    print("== customers ==")
    status, customers = c.call("GET", "/api/v1/customers")
    items = (customers or {}).get("items", []) if isinstance(customers, dict) else []
    _record(
        "GET /customers",
        status != -1 and isinstance(customers, dict) and "items" in customers,
        f"status={status} count={len(items)}",
    )

    status, filtered = c.call("GET", f"/api/v1/customers?search=zzz-{stamp}")
    _record("GET /customers?search=", status != -1, f"status={status}")

    # ---------------------------------------------------------- orders ----
    print()
    print("== orders ==")
    status, orders = c.call("GET", "/api/v1/orders")
    _record(
        "GET /orders",
        status != -1 and isinstance(orders, dict) and "items" in orders,
        f"status={status}",
    )

    status, by_cust = c.call("GET", f"/api/v1/orders?customer_id={uuid.uuid4()}")
    _record(
        "GET /orders?customer_id= (the N-02 filter)",
        status != -1,
        f"status={status}",
    )

    # --------------------------------------------------------- search -----
    print()
    print("== search / jobs / ai ==")
    status, hits = c.call("GET", "/api/v1/search?q=smoke")
    _record("GET /search", status != -1 and isinstance(hits, list), f"status={status}")

    status, jobs = c.call("GET", "/api/v1/jobs")
    _record("GET /jobs", status != -1, f"status={status}")

    status, agents = c.call("GET", "/api/v1/ai/agents")
    _record("GET /ai/agents", status != -1, f"status={status}")

    status, approvals = c.call("GET", "/api/v1/ai/approvals")
    _record(
        "GET /ai/approvals",
        status != -1 and isinstance(approvals, dict) and "items" in approvals,
        f"status={status}",
    )

    # ------------------------------------------------------- cleanup ------
    print()
    if args.keep:
        print(f"keeping the smoke tenant: slug={slug} email={email}")
    else:
        print("cleaning up:", await _admin_cleanup(slug, email))

    passed = sum(1 for _n, ok, _d in _results if ok)
    total = len(_results)
    print()
    print(f"RESULT: {passed}/{total} checks passed")
    failures = [(n, d) for n, ok, d in _results if not ok]
    if failures:
        print("failures:")
        for name, detail in failures:
            print(f"  - {name} ({detail})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
