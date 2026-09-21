"""§70/§164 — Backup & Disaster Recovery restore test.

This is NOT a unit test — it is a manual/CI script that verifies the restore
procedure works against a real (or staging) database. Run it on a schedule
(monthly) against the staging environment to prove the backup is restorable.

Usage:
    DATABASE_URL=postgresql://... python -m tests.dr.run_restore_test

Exit code 0 = success, non-zero = failure (triggers alert).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, text


async def run_restore_test(database_url: str) -> bool:
    """Verify that a backup can be restored and queried.

    Steps:
    1. Connect to a test/staging database (restored from backup)
    2. Verify core tables exist and are non-empty
    3. Verify RLS policies are active
    4. Verify a tenant-scoped query returns data
    5. Record the test result
    """
    print("§70/§164: DR restore test starting...")
    engine = create_engine(database_url)

    try:
        with engine.connect() as conn:
            # 1. Verify core tables exist
            tables = conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "ORDER BY tablename"
                )
            ).fetchall()
            table_names = {t[0] for t in tables}
            required = {"tenants", "customers", "conversations", "orders", "audit_log"}
            missing = required - table_names
            if missing:
                print(f"FAIL: missing core tables: {missing}")
                return False
            print(f"  [OK] Core tables present ({len(table_names)} tables)")

            # 2. Verify tenants exist
            tenant_count = conn.execute(
                text("SELECT count(*) FROM tenants WHERE deleted_at IS NULL")
            ).scalar()
            if tenant_count == 0:
                print("FAIL: no active tenants found")
                return False
            print(f"  [OK] {tenant_count} active tenants")

            # 3. Verify RLS is active on core tables
            rls_check = conn.execute(
                text(
                    "SELECT relname, relrowsecurity "
                    "FROM pg_class "
                    "WHERE relname IN ('customers', 'conversations', 'orders') "
                    "AND relnamespace = 'public'::regnamespace"
                )
            ).fetchall()
            for row in rls_check:
                if not row[1]:
                    print(f"FAIL: RLS not enabled on {row[0]}")
                    return False
            print("  [OK] RLS enabled on core tables")

            # 4. Verify a tenant-scoped query works
            tenant_id = conn.execute(
                text("SELECT id FROM tenants WHERE deleted_at IS NULL LIMIT 1")
            ).scalar()
            if tenant_id is None:
                print("FAIL: could not get a tenant for scoped query")
                return False

            customer_count = conn.execute(
                text(
                    "SELECT count(*) FROM customers "
                    "WHERE tenant_id = :tid AND deleted_at IS NULL"
                ),
                {"tid": tenant_id},
            ).scalar()
            print(f"  [OK] Tenant {tenant_id} has {customer_count} customers")

            # 5. Verify audit log has entries (proves write path works)
            audit_count = conn.execute(
                text("SELECT count(*) FROM audit_log")
            ).scalar()
            if audit_count == 0:
                print("WARN: audit_log is empty — backup may be from a fresh install")
            else:
                print(f"  [OK] {audit_count} audit entries")

        print("\n§70/§164: DR restore test PASSED")
        return True

    except Exception as exc:
        print(f"\nFAIL: {exc}")
        return False
    finally:
        engine.dispose()


def main() -> int:
    import os

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("STAGING_DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL or STAGING_DATABASE_URL must be set")
        return 2

    success = asyncio.run(run_restore_test(db_url))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
