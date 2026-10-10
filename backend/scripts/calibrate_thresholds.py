"""Calibrate the vision decision thresholds on a labelled corpus (§12.2/§21).

Usage::

    python scripts/calibrate_thresholds.py <tenant_id> <corpus.csv> [--limit N]

corpus.csv rows: ``image_path,label`` — label is a product UUID or the
literal ``out_of_catalog``. Paths are relative to the CSV's directory (or
absolute). Requires the vision provider keys (AI_EMBEDDING_VISION_API_KEY /
AI_RERANKER_API_KEY) and the tenant's catalog already indexed
(scripts/index_product_images.py).

Prints the §21 acceptance table (top-1/top-3 with and without the reranker,
out-of-catalog honesty, confident-wrong rate) and the PROPOSED thresholds.
Changing vision/thresholds.py with the measured numbers is a SEPARATE,
reviewed commit — this script only measures.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import sys
import uuid
from pathlib import Path

from _bootstrap import load_settings, session_factory

from app.core.errors import ExternalProviderError
from app.modules.ai.agents.customer.evaluation.metrics import (
    CaseResult,
    confident_wrong_rate,
    hit_at_k,
    out_of_catalog_honesty,
    propose_thresholds,
)
from app.modules.ai.agents.customer.vision.reranker import rerank_candidates
from app.modules.ai.agents.customer.vision.retrieval import retrieve_candidates

MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def _data_url(path: Path) -> str:
    mime = MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"unsupported image type: {path.suffix}")
    raw = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{raw}"


async def run(tenant_id: uuid.UUID, corpus: Path, limit: int, *, no_rerank: bool) -> int:
    load_settings(
        require=("ai_embedding_vision_api_key",),
        script="scripts/calibrate_thresholds.py",
    )
    with corpus.open(newline="", encoding="utf-8") as handle:
        rows = [
            (corpus.parent / image_path.strip(), label.strip())
            for image_path, label in csv.reader(handle)
            if image_path.strip() and not image_path.startswith("#")
        ][:limit]

    cases: list[CaseResult] = []
    failures: list[str] = []
    factory = session_factory()
    async with factory() as session:
        from app.core.db import bind_tenant

        await bind_tenant(session, tenant_id)
        for index, (path, label) in enumerate(rows, start=1):
            try:
                data_url = _data_url(path)
                candidates = await retrieve_candidates(session, tenant_id, image_url=data_url)
                scores: list[float] = []
                ranked = [str(c.product_id) for c in candidates]
                if candidates and not no_rerank:
                    try:
                        scored = await rerank_candidates(
                            candidates,
                            query_image=data_url,
                            session=session,
                            tenant_id=tenant_id,
                        )
                        ranked = [str(c.product_id) for c, _ in scored]
                        scores = [s for _, s in scored]
                    except ExternalProviderError as exc:
                        failures.append(f"row {index}: rerank failed: {exc}")
                out_of_catalog = label.lower() == "out_of_catalog"
                top_score = scores[0] if scores else 0.0
                cases.append(
                    CaseResult(
                        label_product_id=None if out_of_catalog else label,
                        ranked_product_ids=ranked,
                        scores=scores,
                        confident_wrong=out_of_catalog and top_score >= 0.62,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one bad row must not end the run
                failures.append(f"row {index} ({path.name}): {exc}")

    in_catalog = [c for c in cases if c.label_product_id is not None]
    print(f"corpus: {len(cases)} evaluated, {len(failures)} row failures")
    print(f"top-1 (with rerank):    {hit_at_k(cases, 1):.3f}")
    print(f"top-3 (with rerank):    {hit_at_k(cases, 3):.3f}")
    print(f"out-of-catalog honesty: {out_of_catalog_honesty(cases):.3f}")
    print(f"confident-wrong rate:   {confident_wrong_rate(cases):.3f}")
    if not no_rerank:
        print(
            f"top-1 (embedding only): {hit_at_k(in_catalog, 1):.3f}  "
            f"[rerank removed by construction — embedding order]"
        )
    print(f"PROPOSED thresholds:    {propose_thresholds(cases)}")
    for failure in failures[:10]:
        print(f"  {failure}")
    return 0 if cases else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the vision stack on a labelled corpus.")
    parser.add_argument("tenant_id", type=uuid.UUID)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--no-rerank", action="store_true", help="measure the embedding-only path")
    args = parser.parse_args()
    return await run(args.tenant_id, args.corpus, args.limit, no_rerank=args.no_rerank)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
