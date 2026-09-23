"""Converge `metric_definitions` onto the canonical registry for EXISTING tenants.

The `metric_definitions` table is the tenant-visible audit copy of the in-code
``MetricRegistry`` (spec §167). Two facts made that copy fictional before this:

* ``seed_definitions`` had no caller, so a live tenant had ZERO rows — the table
  mirrored nothing; and
* it was insert-only (``ON CONFLICT DO NOTHING``), so even a tenant that somehow
  had rows could never receive a definition whose text / source / rules changed.

Both are fixed on the code path (provisioning now seeds, and seeding converges).
But tenants provisioned BEFORE that change have rows that predate it — either no
rows, or rows frozen at an old definition. This script pushes them to match the
registry.

It calls ``seed_definitions`` directly, which is the same converging upsert
provisioning uses, so:

* a tenant with no rows gets the full registry inserted;
* a tenant whose row drifted from the registry has that row UPDATED;
* a tenant already in sync is left untouched (0 writes).

It touches ONLY ``metric_definitions`` — no calendar, no SLA, no subscription —
so unlike `backfill_tenant_defaults.py` it has no commercial side effect and is
safe on the whole estate.

**DRY-RUN BY DEFAULT**, because it is meant to run against production: it reports
what each tenant would change and writes nothing unless you pass ``--apply``.

    # see what would happen
    ENVIRONMENT=production python scripts/backfill_metric_definitions.py

    # actually converge every tenant
    ENVIRONMENT=production python scripts/backfill_metric_definitions.py --apply

Idempotent: re-running writes nothing once every tenant mirrors the registry.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid as _uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _bootstrap import load_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant


async def _tenant_ids(session: AsyncSession) -> list[tuple[str, str]]:
    """(id, slug) for every tenant. `tenants` carries no RLS, so no GUC needed."""
    from app.modules.identity.models import Tenant

    rows = (
        await session.execute(select(Tenant.id, Tenant.slug).order_by(Tenant.created_at))
    ).all()
    return [(str(tid), slug) for tid, slug in rows]


async def _converge(session: AsyncSession, tenant_id: str) -> int:
    """Seed/converge one tenant inside the caller's transaction, with the GUC bound.

    Returns the number of rows the converging upsert wrote (0 = already mirrors
    the registry). Imported lazily so this ops script never forces the web-app
    config at module import time.
    """
    from app.modules.platform.metrics import seed_definitions

    await bind_tenant(session, _uuid.UUID(tenant_id))
    return await seed_definitions(session, _uuid.UUID(tenant_id))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it this is a dry run.",
    )
    args = parser.parse_args()

    # `load_settings` fails closed on an unstated ENVIRONMENT rather than guessing:
    # this runs against production, so assuming "local" would be the one guess
    # that matters.
    settings = load_settings(
        require=("database_url_admin",), script="scripts/backfill_metric_definitions.py"
    )
    engine = create_async_engine(
        settings.database_url_admin, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    print(f"environment: {settings.environment}")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    async with factory() as session:
        tenants = await _tenant_ids(session)

    if not tenants:
        print("no tenants found")
        await engine.dispose()
        return 0

    total_written = 0
    for tenant_id, slug in tenants:
        # Dry run: seed_definitions is idempotent and reads the registry, so
        # asking it inside a rolled-back transaction reports the honest count
        # without persisting a byte.
        async with factory() as session:
            async with session.begin():
                wrote = await _converge(session, tenant_id)
                if not args.apply:
                    await session.rollback()

        total_written += wrote
        state = "in sync" if wrote == 0 else f"{wrote} row(s) written"
        print(f"  {slug:<24} {state}")

    print()
    verb = "converged" if args.apply else "would converge"
    print(f"{verb}: {total_written} row(s) across {len(tenants)} tenant(s)")
    if not args.apply:
        print("nothing was written — re-run with --apply")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
