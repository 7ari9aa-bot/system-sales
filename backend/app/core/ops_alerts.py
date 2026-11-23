"""Operator alerts: push "something is broken" to a chat webhook (M6).

Tenants already see their own channel problems in the app (`channel_problems` and the owner bell).
What nobody saw was the operator's side: an unhandled 500, a webhook that exhausted its retries.
Those were a log line, so the first sign of an outage was a customer.

This is deliberately small and vendor-neutral. One setting, ``OPS_ALERT_WEBHOOK_URL``, takes any
incoming-webhook URL (Slack, Discord, Mattermost, an ntfy or Telegram relay). Unset means off:
nothing is sent, nothing is probed.

Guarantees, all tested:

* Never raises into the caller. An alert is a courtesy; the request or the worker is the job.
* Never blocks it for long: a short timeout, and the 500 handler schedules the send in the
  background instead of awaiting it.
* Never floods. A fingerprint is sent once per cooldown (Redis, shared by every worker), and an
  hourly cap bounds the total. With Redis down it falls back to a per-process memory, so the cap
  still holds.
* Never leaks. Text is run through the secret redactor and clipped, and the message names the kind
  of failure, the route and the request id, never a payload, a row value or a token.
* Never becomes an open proxy: the URL must be public (SSRF guard) and is checked at send time.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import httpx

from app.core.config import get_settings
from app.core.log_redaction import redact

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 3.0
_MAX_TEXT = 1500
_KEY_PREFIX = "ops_alert:"

#: In-process fallback state, used when Redis cannot be reached: {fingerprint: sent_at}, and the
#: send times inside the last hour. It makes the cap hold per process rather than not at all.
_seen_local: dict[str, float] = {}
_sent_local: list[float] = []

#: Strong references to in-flight background sends, so they are not collected mid-flight.
_pending: set[asyncio.Task] = set()


def _client_class():
    """The HTTP client class; a seam so tests replace only THIS module's client."""
    return httpx.AsyncClient


def _reset_for_tests() -> None:
    _seen_local.clear()
    _sent_local.clear()
    _pending.clear()


def alerts_enabled() -> bool:
    return bool((get_settings().ops_alert_webhook_url or "").strip())


def fingerprint(kind: str, where: str) -> str:
    """Same failure in the same place is the same alert; ids and values never enter it."""
    return hashlib.sha256(f"{kind}\x00{where}".encode()).hexdigest()[:20]


def _clean(value: object, limit: int = 200) -> str:
    text = "".join(ch for ch in str(value) if ch.isprintable() or ch == " ")
    return redact(text)[:limit]


def format_alert(kind: str, where: str, detail: str = "", request_id: str = "") -> str:
    env = _clean(get_settings().environment, 20)
    lines = [f"[{env}] {_clean(kind, 80)}", f"where: {_clean(where)}"]
    if detail:
        lines.append(f"detail: {_clean(detail, 300)}")
    if request_id:
        lines.append(f"request_id: {_clean(request_id, 64)}")
    return "\n".join(lines)[:_MAX_TEXT]


def _local_allows(fp: str, cooldown: int, per_hour: int) -> bool:
    now = time.monotonic()
    last = _seen_local.get(fp)
    if last is not None and now - last < cooldown:
        return False
    _sent_local[:] = [t for t in _sent_local if now - t < 3600]
    if len(_sent_local) >= per_hour:
        return False
    _seen_local[fp] = now
    _sent_local.append(now)
    return True


async def _allowed(fp: str) -> bool:
    """Whether this alert may go out now: not repeated inside the cooldown, under the hourly cap."""
    settings = get_settings()
    cooldown = max(1, int(settings.ops_alert_cooldown_seconds))
    per_hour = max(1, int(settings.ops_alert_max_per_hour))
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        # SET NX is the cooldown: only the first caller in the window gets it, across workers.
        if not await redis.set(f"{_KEY_PREFIX}fp:{fp}", "1", ex=cooldown, nx=True):
            return False
        hour = int(time.time() // 3600)
        key = f"{_KEY_PREFIX}hour:{hour}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3700)
        return count <= per_hour
    except Exception:  # noqa: BLE001 - Redis down must not turn into silence or a flood
        return _local_allows(fp, cooldown, per_hour)


async def send_alert(kind: str, where: str, detail: str = "", request_id: str = "") -> bool:
    """Send one operator alert. True only when it was delivered. Never raises."""
    try:
        url = (get_settings().ops_alert_webhook_url or "").strip()
        if not url:
            return False
        from app.core.net_guard import assert_public_url

        assert_public_url(url)
        if not await _allowed(fingerprint(kind, where)):
            return False
        text = format_alert(kind, where, detail, request_id)
        async with _client_class()(timeout=_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(url, json={"text": text, "content": text})
        if response.status_code >= 300:
            # The status only: the response body and the URL are never logged.
            logger.warning("ops_alert.rejected status=%s", response.status_code)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - an alert must never break its caller
        logger.warning("ops_alert.failed error=%s", type(exc).__name__)
        return False


def fire_and_forget(kind: str, where: str, detail: str = "", request_id: str = "") -> None:
    """Schedule an alert without making the caller wait for it. Safe with no running loop."""
    if not alerts_enabled():
        return
    try:
        task = asyncio.get_running_loop().create_task(send_alert(kind, where, detail, request_id))
    except RuntimeError:
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)
