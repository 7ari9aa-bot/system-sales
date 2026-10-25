"""Rebuild ``pos_daily_sales`` so every closed day sits under the MERCHANT's calendar date.

Until now the close event and the projection counted a day in UTC, while every report counts it in
the shop's zone (``tenants.timezone``). For a Cairo shop a close between 00:00 and 02:00 local was
filed under the previous date. New closes now use the shop's date; this script fixes the rows
already written.

Safe to run repeatedly: the projection is RECOMPUTED from the ledgers (receipts and return lines),
never incremented, so a second run rewrites the same truth. It touches only ``pos_daily_sales``.

    python scripts/backfill_pos_daily_sales.py            # dry run: prints what would change
    python scripts/backfill_pos_daily_sales.py --apply    # rewrites the projection
    python scripts/backfill_pos_daily_sales.py --apply --tenant <slug>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _bootstrap import load_settings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.modules.analytics.timekit import resolve_timezone
from app.modules.identity.models import Tenant
from app.modules.pos.models import PosDailySales, PosSession
from app.modules.pos.service import PosService


async def _plan(session: AsyncSession, tenant_id, tz) -> tuple[set[date], set[date]]:
    """(dates the ledgers say should exist, dates the projection currently holds)."""
    zone = resolve_timezone(tz)
    wanted = {
        d
        for (d,) in (
            await session.execute(
                select(func.date(func.timezone(zone, PosSession.closed_at)))
                .where(PosSession.tenant_id == tenant_id, PosSession.status == "CLOSED")
                .distinct()
            )
        ).all()
        if d is not None
    }
    held = {
        d
        for (d,) in (
            await session.execute(
                select(PosDailySales.business_date)
                .where(PosDailySales.tenant_id == tenant_id)
                .distinct()
            )
        ).all()
    }
    return wanted, held


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--tenant", help="only this tenant slug")
    args = parser.parse_args()

    settings = load_settings(require=("database_url_admin",), script="backfill_pos_daily_sales")
    engine = create_async_engine(
        settings.database_url_admin, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    print(f"environment: {settings.environment}  mode: {'APPLY' if args.apply else 'dry run'}")

    changed = 0
    async with factory() as session:
        query = select(Tenant.id, Tenant.slug, Tenant.timezone).order_by(Tenant.created_at)
        if args.tenant:
            query = query.where(Tenant.slug == args.tenant)
        tenants = (await session.execute(query)).all()

    for tenant_id, slug, tz in tenants:
        async with factory() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                wanted, held = await _plan(session, tenant_id, tz)
                stale, missing = sorted(held - wanted), sorted(wanted - held)
                if not stale and not missing:
                    continue
                print(
                    f"{slug} ({tz or 'UTC'}): "
                    f"{len(stale)} date(s) with no closed day {[str(d) for d in stale]}, "
                    f"{len(missing)} closed date(s) not projected {[str(d) for d in missing]}"
                )
                changed += 1
                if not args.apply:
                    await session.rollback()
                    continue
                # Rebuild every date in either set: a stale date has its rows removed (no
                # session closes on it any more), a missing date gets them (re)written.
                for day in sorted(held | wanted):
                    await PosService.upsert_daily_projection(session, tenant_id, business_date=day)
    print(f"{'rewrote' if args.apply else 'would rewrite'} {changed} tenant(s)")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
