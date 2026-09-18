"""Time-sortable UUIDv7 generation for high-volume tables.

Spec §142: UUIDv7 (time-sortable) for high-volume entities so B-tree indexes
stay locally-ordered under insert load and cursor pagination keys stay cheap.
Adopted for ALL NEW tables; existing uuid4 PKs stay (no churn).

Python 3.14 stdlib has no uuid7; implemented per RFC 9562: 48-bit unix-ts_ms
prefix + version/variant bits + 74 random bits. Monotonic within the process
via a per-ms counter to guarantee strict ordering of same-ms ids.
"""

from __future__ import annotations

import os
import time
import uuid

_last_ms = 0
_last_rand = 0


def uuid7() -> uuid.UUID:
    """Generate a RFC 9562 UUIDv7 (unix-ts_ms based, monotonic per process)."""
    global _last_ms, _last_rand

    ms = time.time_ns() // 1_000_000
    if ms == _last_ms:
        _last_rand += 1  # monotonic within the same millisecond
    else:
        _last_ms = ms
        _last_rand = int.from_bytes(os.urandom(5), "big") & ((1 << 40) - 1)

    # 48-bit timestamp | ver(4) | 12 bits rand_a | var(2) | 62 bits rand_b
    rand_a = _last_rand & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # variant
    value |= rand_b
    return uuid.UUID(int=value)


def uuid7_str() -> str:
    return str(uuid7())
