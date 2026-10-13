"""Quarterly DR Restore Drill — automates RUNBOOK.md "Backups & DR" (R-F3).

Usage:
    cd backend
    .venv/Scripts/python scripts/restore_drill.py --target-url <RESTORED_DB_URL>
    .venv/Scripts/python scripts/restore_drill.py --target-url <URL> --app-url <APP_ROLE_URL>

The target is a RESTORED COPY (a scratch Supabase project or a restored branch),
never production. Checks executed against it:

    1. Schema current      — the restored DB is at this code's alembic head.
    2. Row counts          — the business tables exist and are readable.
    3. Outbox integrity    — status distribution + rows stranded in 'publishing'.
    4. Event log integrity — published events carry a type and a payload.
    5. Invoice immutability— the frozen-snapshot guards survived the restore.
    6. RLS isolation       — scripts/rls_smoke_test.py run AGAINST THE TARGET.

Design notes that matter (each was a real defect in the first version):

* **The RLS check runs against the target, not the ambient .env.** The smoke
  test reads DATABASE_URL_APP_ADMIN, so this script passes that value into the
  child process. Without it the drill silently validated whatever database the
  operator's .env pointed at — it could "pass" a restore it never checked.
* **A check that did not run is SKIPPED, never PARTIAL.** The first version
  looked for the literal string "7/7 PASS", which rls_smoke_test.py has never
  printed (it prints one `[PASS] <name>` line per assertion and exits non-zero
  on failure). That criterion could never match, so the check reported PARTIAL
  forever while the summary still claimed everything passed.
* **Any FAIL fails the drill.** Failures are aggregated and the exit code is 1.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from _bootstrap import load_settings  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.schema_guard import assert_schema_current  # noqa: E402

# One `[PASS]` / `[FAIL]` line per assertion in scripts/rls_smoke_test.py.
_SMOKE_LINE = re.compile(r"^\s*\[(PASS|FAIL)\]\s", re.MULTILINE)

# The frozen-snapshot guards created by migrations e7a8b9c0d1e2 / a9b0c1d2e3f4.
_INVOICE_GUARD_FUNCTIONS = ("invoices_frozen_snapshot_guard", "invoices_truncate_guard")

# Business tables a restore must carry. Every name was checked against the
# models; the first version counted "outbox", which does not exist (the table is
# outbox_events), so its outbox check failed on every run and said nothing.
_COUNTED_TABLES = (
    "tenants",
    "users",
    "customers",
    "conversations",
    "messages",
    "orders",
    "invoices",
    "outbox_events",
    "event_log",
)


def parse_smoke_stdout(stdout: str) -> tuple[int, int]:
    """(passed, failed) from rls_smoke_test.py's per-assertion verdict lines."""
    verdicts = _SMOKE_LINE.findall(stdout)
    return verdicts.count("PASS"), verdicts.count("FAIL")


def summarize(checks: dict[str, dict[str, object]]) -> str:
    """FAIL if any check failed; otherwise PASS (skips are reported, not hidden)."""
    if any(check.get("status") == "FAIL" for check in checks.values()):
        return "FAIL"
    return "PASS"


def derive_app_url(target_url: str, app_url_from_settings: str) -> str | None:
    """Point the app-role DSN at the restored host, keeping its credentials.

    A restore of the same cluster carries the `sales_app` role, so the role's
    credentials are unchanged and only host/port/database need to move. Returns
    None when either side is unusable — the caller then reports the RLS check as
    SKIPPED rather than guessing a DSN.
    """
    if not target_url or not app_url_from_settings:
        return None
    try:
        target, app = urlsplit(target_url), urlsplit(app_url_from_settings)
    except ValueError:
        return None
    if not target.hostname or not app.hostname or not app.username:
        return None
    host_port = f"{target.hostname}:{target.port}" if target.port else target.hostname
    netloc = f"{app.username}:{app.password}@{host_port}" if app.password else None
    if netloc is None:
        netloc = f"{app.username}@{host_port}"
    return urlunsplit((app.scheme, netloc, target.path or app.path, "", ""))


def run_rls_smoke(app_url: str | None) -> dict[str, object]:
    """Run the RLS smoke test against the TARGET database."""
    if not app_url:
        return {
            "status": "SKIPPED",
            "reason": (
                "no app-role URL for the target: pass --app-url, or set "
                "DATABASE_URL_APP_ADMIN so it can be re-pointed at the restored host"
            ),
        }
    smoke_script = Path(__file__).resolve().parent / "rls_smoke_test.py"
    if not smoke_script.exists():
        return {"status": "FAIL", "reason": f"missing {smoke_script.name}"}
    try:
        completed = subprocess.run(
            [sys.executable, str(smoke_script)],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            # Environment variables outrank .env in pydantic-settings, so this
            # pins the child to the restored copy and never to production.
            env={
                **os.environ,
                "DATABASE_URL_APP_ADMIN": app_url,
                "DATABASE_URL_APP": app_url,
            },
        )
    except Exception as exc:  # noqa: BLE001 — a drill reports, it does not crash
        return {"status": "FAIL", "reason": f"could not run {smoke_script.name}: {exc}"}

    passed, failed = parse_smoke_stdout(completed.stdout)
    detail: dict[str, object] = {
        "returncode": completed.returncode,
        "assertions_passed": passed,
        "assertions_failed": failed,
        "stdout_tail": completed.stdout[-400:],
    }
    if completed.returncode != 0 or failed:
        detail["status"] = "FAIL"
        return detail
    if passed == 0:
        # Exit code 0 with no verdict lines means the script asserted nothing —
        # a broken check, not a passing one.
        detail["status"] = "FAIL"
        detail["reason"] = "smoke test exited 0 but printed no [PASS]/[FAIL] verdicts"
        return detail
    detail["status"] = "PASS"
    return detail


async def run_restore_drill(db_url: str, app_url: str | None) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    try:
        # 1. Schema current
        try:
            await assert_schema_current(engine)
            checks["schema_current"] = {"status": "PASS", "detail": "at this code's head"}
        except Exception as exc:  # noqa: BLE001
            checks["schema_current"] = {"status": "FAIL", "reason": str(exc)}

        async with engine.connect() as conn:
            # 2. Row counts — a missing table is a FAIL, not a swallowed string
            counts: dict[str, object] = {}
            unreadable: list[str] = []
            for table in _COUNTED_TABLES:
                try:
                    result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    counts[table] = int(result.scalar() or 0)
                except Exception as exc:  # noqa: BLE001
                    counts[table] = "ERROR"
                    unreadable.append(f"{table} ({type(exc).__name__})")
            if unreadable:
                checks["row_counts"] = {
                    "status": "FAIL",
                    "reason": "unreadable tables: " + ", ".join(unreadable),
                    "counts": counts,
                }
            else:
                checks["row_counts"] = {"status": "PASS", "counts": counts}

            # 3. Outbox integrity (the table is outbox_events — see _COUNTED_TABLES)
            try:
                result = await conn.execute(
                    text("SELECT status, COUNT(*) FROM outbox_events GROUP BY status")
                )
                distribution = {row[0]: int(row[1]) for row in result.fetchall()}
                stranded = await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM outbox_events WHERE status = 'publishing' "
                        "AND created_at < now() - interval '10 minutes'"
                    )
                )
                stranded_count = int(stranded.scalar() or 0)
                checks["outbox_integrity"] = {
                    "status": "PASS" if stranded_count == 0 else "FAIL",
                    "distribution": distribution,
                    "stranded_publishing": stranded_count,
                }
            except Exception as exc:  # noqa: BLE001
                checks["outbox_integrity"] = {"status": "FAIL", "reason": str(exc)}

            # 4. Event log integrity
            try:
                result = await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM event_log "
                        "WHERE event_type IS NULL OR payload IS NULL"
                    )
                )
                malformed = int(result.scalar() or 0)
                checks["event_log_integrity"] = {
                    "status": "PASS" if malformed == 0 else "FAIL",
                    "malformed_rows": malformed,
                }
            except Exception as exc:  # noqa: BLE001
                checks["event_log_integrity"] = {"status": "FAIL", "reason": str(exc)}

            # 5. Invoice immutability guards survived the restore
            try:
                result = await conn.execute(
                    text(
                        "SELECT p.proname FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_proc p ON p.oid = t.tgfoid "
                        "WHERE c.relname = 'invoices' AND NOT t.tgisinternal"
                    )
                )
                present = sorted({row[0] for row in result.fetchall()})
                missing = [fn for fn in _INVOICE_GUARD_FUNCTIONS if fn not in present]
                checks["invoice_immutability"] = {
                    "status": "PASS" if not missing else "FAIL",
                    "guards_present": present,
                    "guards_missing": missing,
                }
            except Exception as exc:  # noqa: BLE001
                checks["invoice_immutability"] = {"status": "FAIL", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # The target could not be reached at all. That is a failed drill, and it
        # must be a reported check rather than a traceback the operator has to
        # read: a drill that crashes tells you nothing about the restore.
        checks["database_connection"] = {"status": "FAIL", "reason": str(exc)}
    finally:
        await engine.dispose()

    # 6. RLS isolation, against the target
    checks["rls_smoke_test"] = run_rls_smoke(app_url)

    return {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "target_host": db_url.split("@")[-1] if "@" in db_url else db_url,
        "checks": checks,
        "status": summarize(checks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Disaster Recovery restore drill (R-F3)")
    parser.add_argument("--target-url", help="RESTORED database URL to verify")
    parser.add_argument(
        "--app-url",
        help=(
            "app-role (sales_app) URL on the restored database, needed for the RLS "
            "check; defaults to DATABASE_URL_APP_ADMIN re-pointed at the target host"
        ),
    )
    args = parser.parse_args()

    settings = load_settings(script="scripts/restore_drill.py")
    db_url = args.target_url or settings.database_url_admin or settings.database_url
    if not db_url:
        sys.exit("Error: no target database URL (pass --target-url)")

    app_url = args.app_url or derive_app_url(db_url, settings.database_url_app_admin)

    print(f"=== DR restore drill against: {db_url.split('@')[-1]} ===")
    report = asyncio.run(run_restore_drill(db_url, app_url))
    print(json.dumps(report, indent=2))

    raw_checks = report["checks"]
    checks: dict[str, dict[str, object]] = raw_checks if isinstance(raw_checks, dict) else {}
    tally: dict[str, int] = {}
    for check in checks.values():
        status = str(check.get("status"))
        tally[status] = tally.get(status, 0) + 1

    summary = ", ".join(f"{count} {status}" for status, count in sorted(tally.items()))
    print(f"\n{len(checks)} checks: {summary}")

    if report["status"] == "PASS":
        if tally.get("SKIPPED"):
            print("WARNING: drill incomplete — see the SKIPPED entry above.")
        else:
            print("RESTORE DRILL SUCCESSFUL: every check passed.")
        return
    print("RESTORE DRILL FAILED: see the FAIL entries above.")
    sys.exit(1)


if __name__ == "__main__":
    main()
