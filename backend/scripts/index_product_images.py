"""Embed approved product images for one tenant (Customer Agent §12.6).

Usage::

    python scripts/index_product_images.py <tenant_id> [--batch-size N]

Requires the vision embedding credentials in the environment (or
backend/.env): AI_EMBEDDING_VISION_BASE_URL / _API_KEY / _MODEL /
_DIMENSIONS. Idempotent — safe to re-run after catalog edits; only images of
sellable products are embedded, and a changed embedding model means a full
re-index by construction (the UNIQUE constraint pins vector to model).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from _bootstrap import load_settings, session_factory

from app.modules.ai.agents.customer.vision.indexer import index_product_images


async def main() -> int:
    parser = argparse.ArgumentParser(description="Embed approved product images for one tenant.")
    parser.add_argument("tenant_id", type=uuid.UUID)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    load_settings(
        require=("ai_embedding_vision_api_key",),
        script="scripts/index_product_images.py",
    )
    factory = session_factory()
    async with factory() as session:
        # The governed embedding path writes model_calls and budget
        # reservations — RLS-guarded rows that need the tenant GUC bound.
        from app.core.db import bind_tenant

        await bind_tenant(session, args.tenant_id)
        stats = await index_product_images(session, args.tenant_id, batch_size=args.batch_size)
        await session.commit()
    print(f"indexed: {stats['indexed']} image(s) in {stats['batches']} batch(es)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
