"""Messaging hot-path load test — hammers the public webchat ingest endpoint.

Usage (backend venv, backend cwd, API reachable):
    .venv/bin/python scripts/load_test.py --url http://localhost:8000 \
        --public-key <webchat_public_key> --concurrency 20 --total 500

Asserts p95 latency < 800ms and error rate < 1% for the hot path target.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid

import httpx


async def worker(
    client: httpx.AsyncClient, url: str, public_key: str, n: int, latencies: list
) -> None:
    for _ in range(n):
        body = {
            "session_key": f"load-{uuid.uuid4().hex[:12]}",
            "body": "رسالة اختبار حمل",
            "client_message_id": f"load-{uuid.uuid4().hex[:12]}",
        }
        start = time.perf_counter()
        try:
            response = await client.post(f"{url}/webchat/{public_key}/messages", json=body)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            if response.status_code >= 400:
                latencies.append(None)  # counted as error marker
        except Exception:
            latencies.append(None)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--total", type=int, default=500)
    args = parser.parse_args()

    latencies: list[float | None] = []
    per_worker = args.total // args.concurrency
    async with httpx.AsyncClient(timeout=30) as client:
        started = time.perf_counter()
        await asyncio.gather(
            *[
                worker(client, args.url, args.public_key, per_worker, latencies)
                for _ in range(args.concurrency)
            ]
        )
        wall = time.perf_counter() - started

    errors = sum(1 for value in latencies if value is None)
    ok_values = [value for value in latencies if value is not None]
    ok_values.sort()
    p50 = ok_values[len(ok_values) // 2] if ok_values else 0
    p95 = ok_values[int(len(ok_values) * 0.95)] if ok_values else 0
    error_rate = errors / len(latencies) if latencies else 1

    print(f"total={len(latencies)} ok={len(ok_values)} errors={errors} ({error_rate:.1%})")
    print(f"wall={wall:.1f}s rps={len(latencies) / wall:.1f} p50={p50:.0f}ms p95={p95:.0f}ms")

    failed = error_rate >= 0.01 or p95 >= 800
    print("VERDICT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
