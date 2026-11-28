"""Meta's throughput cap for ONE WhatsApp number: 20 messages per second.

Meta documents a limit of 20 messages per second per phone number on the Cloud API, and the same
cap applies to a coexistence number. Nothing enforced it: a campaign, a burst of AI replies or a
retry storm could push a number over the cap, and Meta answers with 130429 ("cloud api message rate
limit hit") — a send the merchant sees as failed even though the message was fine.

The limit is PER NUMBER, not per workspace: a shop with two numbers has 20 each, and one busy number
must not slow another. It is also shared across every worker process, so the budget lives in Redis
and not in memory.

Pacing, not refusing: the caller waits for the next slot (at most a few seconds) and only gives up
with a retryable error when the wait would be longer than that — at which point the worker's own
backoff is the right place to try again.

If Redis is unavailable the cap is not enforced here. That is deliberate and safe: Meta enforces the
same limit and says so itself, so a missing limiter costs a 130429, never a wrong message.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.errors import ExternalProviderError

logger = logging.getLogger(__name__)

#: Meta's documented ceiling for one phone number.
MESSAGES_PER_SECOND = 20
WINDOW_SECONDS = 1.0
#: How long one send may wait for a slot before it is handed back to the worker's backoff.
MAX_WAIT_SECONDS = 5.0
#: Redis key prefix the limiter uses, so the read-only view below counts the same budget.
KEY_PREFIX = "wa-mps"


def _limiter(client):
    from app.core.ratelimit import RateLimiter

    return RateLimiter(
        client,
        limit=MESSAGES_PER_SECOND,
        window_seconds=WINDOW_SECONDS,
        prefix=KEY_PREFIX,
    )


async def acquire(phone_number_id: str, *, client=None) -> float:
    """Wait for one send slot on this number. Returns the seconds actually waited.

    A denied slot is retried after exactly the time the window says, so the caller paces itself
    instead of hammering Meta with sends that would be rejected anyway.
    """
    from app.core.redis import get_redis_or_none

    redis_client = client if client is not None else get_redis_or_none()
    if redis_client is None or not phone_number_id:
        return 0.0
    limiter = _limiter(redis_client)
    waited = 0.0
    started = time.monotonic()
    while True:
        try:
            result = await limiter.allow(str(phone_number_id))
        except Exception:  # noqa: BLE001 - a limiter fault must not stop a legal send
            logger.warning("whatsapp.throughput_unavailable number=%s", phone_number_id)
            return waited
        if result.allowed:
            return waited
        remaining_budget = MAX_WAIT_SECONDS - (time.monotonic() - started)
        delay = max(0.01, float(result.retry_after_seconds or 0.0))
        if delay > remaining_budget:
            raise ExternalProviderError(
                "This WhatsApp number is sending at its maximum rate (20 messages a second). "
                "The message will be retried.",
                retryable=True,
            )
        await asyncio.sleep(delay)
        waited += delay


async def usage(phone_number_id: str, *, client=None) -> dict:
    """How much of this number's 20-per-second budget is in use right now.

    Read-only, for the operator: when Meta answers 130429 the first question is always "are we
    sending too fast, or is something else wrong?". Without this the answer was a guess. It reports
    ``None`` (state ``unknown``) rather than a fake zero when Redis is not tracking the number, so a
    missing limiter is never mistaken for an idle number.
    """
    payload: dict = {
        "limit_per_second": MESSAGES_PER_SECOND,
        "window_seconds": WINDOW_SECONDS,
        "current": None,
        "remaining": None,
        "headroom_percent": None,
        "state": "unknown",
        "explains_130429": (
            "130429 means this number sent more than 20 messages in one second. At the cap, the "
            "send was paced too hard and a retry will succeed. Below it, the cause is something "
            "else: a restricted number, a policy block or an app-level limit."
        ),
    }
    from app.core.redis import get_redis_or_none

    redis_client = client if client is not None else get_redis_or_none()
    if redis_client is None or not phone_number_id:
        payload["note"] = (
            "The send limiter is not tracking this number (Redis unavailable), so Meta's own cap "
            "is the only limit in force."
        )
        return payload
    now_ms = int(time.time() * 1000)
    window_ms = int(WINDOW_SECONDS * 1000)
    try:
        current = int(
            await redis_client.zcount(f"{KEY_PREFIX}:{phone_number_id}", now_ms - window_ms, now_ms)
        )
    except Exception:  # noqa: BLE001 - a diagnostic must never break the status endpoint
        logger.warning("whatsapp.throughput_read_failed phone_number_id=%s", phone_number_id)
        payload["note"] = "The send limiter could not be read just now."
        return payload
    remaining = max(MESSAGES_PER_SECOND - current, 0)
    payload.update(
        {
            "current": current,
            "remaining": remaining,
            "headroom_percent": int(round(remaining / MESSAGES_PER_SECOND * 100)),
            "state": "at_cap" if remaining == 0 else ("busy" if current >= 15 else "ok"),
        }
    )
    return payload
