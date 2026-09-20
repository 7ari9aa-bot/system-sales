"""Backfill the operational defaults onto EXISTING tenants (review N-11).

`seed_tenant_defaults` runs at `register`, so only NEW tenants get a business
calendar, an SLA policy and a plan. Production has tenants created before that
existed, and they were left with `business_calendars` = 0, `sla_policies` = 0
and `subscriptions` = 0 — so SLA and entitlements were inert on real data.

This is DRY-RUN BY DEFAULT. It prints what it would create and writes nothing
unless you pass `--apply`, because it is meant to be run against production.

    # see what would happen
    ENVIRONMENT=production python scripts/backfill_tenant_defaults.py

    # calendar + SLA policy + AI budget policy only (safe additions)
    ENVIRONMENT=production python scripts/backfill_tenant_defaults.py --apply

    # also bind each tenant to the default plan
    ENVIRONMENT=production python scripts/backfill_tenant_defaults.py --apply --with-subscription

**Why the subscription is opt-in.** Binding an existing tenant to a plan
activates that plan's entitlement allow-list, and `starter` permits only
`whatsapp` and `webchat`. A tenant already using another channel would silently
lose it. A calendar, an SLA policy and a budget policy are pure additions with
no such side effect, so the default is the safe subset and the commercial
decision stays with a human.

Idempotent: re-running creates nothing. Safe to run on a partially-seeded estate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _bootstrap import load_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.modules.identity.bootstrap import seed_tenant_defaults


async def _tenant_ids(session: AsyncSession) -> list[tuple[str, str]]:
    """(id, slug) for every tenant. `tenants` carries no RLS, so no GUC needed."""
    from app.modules.identity.models import Tenant

    rows = (
        await session.execute(select(Tenant.id, Tenant.slug).order_by(Tenant.created_at))
    ).all()
    return [(str(tid), slug) for tid, slug in rows]


async def _backfill(
    session: AsyncSession, tenant_id: str, *, include_subscription: bool
) -> dict:
    """Seed one tenant inside its own transaction, with the GUC bound."""
    import uuid as _uuid

    await bind_tenant(session, _uuid.UUID(tenant_id))
    return await seed_tenant_defaults(
        session, _uuid.UUID(tenant_id), include_subscription=include_subscription
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it this is a dry run.",
    )
    parser.add_argument(
        "--with-subscription",
        action="store_true",
        help=(
            "also bind each tenant to the default plan. This activates the "
            "plan's channel allow-list (starter: whatsapp + webchat only), so "
            "it can restrict a tenant already using another channel."
        ),
    )
    args = parser.parse_args()

    # `load_settings` fails closed on an unstated ENVIRONMENT rather than
    # guessing: this script is meant to run against production, so assuming
    # "local" would be the one guess that matters.
    settings = load_settings(
        require=("database_url_admin",), script="scripts/backfill_tenant_defaults.py"
    )
    url = settings.database_url_admin

    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"environment: {settings.environment}")
    print(f"mode: {mode}")
    print(
        "subscription: "
        + ("yes (plan binding)" if args.with_subscription else "no (safe subset)")
    )
    print()

    async with factory() as session:
        tenants = await _tenant_ids(session)

    if not tenants:
        print("no tenants found")
        await engine.dispose()
        return 0

    total_created = 0
    for tenant_id, slug in tenants:
        if not args.apply:
            # Dry run: report what the seeder WOULD do without writing. It is
            # idempotent, so asking it inside a rolled-back transaction gives
            # the honest answer.
            async with factory() as session:
                async with session.begin():
                    created = await _backfill(
                        session, tenant_id, include_subscription=args.with_subscription
                    )
                    await session.rollback()
        else:
            async with factory() as session:
                async with session.begin():
                    created = await _backfill(
                        session, tenant_id, include_subscription=args.with_subscription
                    )

        made = [k for k, v in created.items() if v]
        total_created += len(made)
        detail = ", ".join(made) if made else "nothing (already seeded)"
        print(f"  {slug:<24} {detail}")

    print()
    print(f"{'created' if args.apply else 'would create'}: {total_created} row(s)")
    if not args.apply:
        print("nothing was written — re-run with --apply")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
