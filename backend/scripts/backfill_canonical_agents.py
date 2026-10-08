"""One-shot operational backfill: provision/sync canonical agents for all tenants.

Idempotent. Safe to run repeatedly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import get_sessionmaker
from app.modules.ai.core.provisioning import backfill_all_tenants


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            result = await backfill_all_tenants(session)
            print(f"Backfill complete: {len(result)} tenants updated: {result}")


if __name__ == "__main__":
    asyncio.run(main())
