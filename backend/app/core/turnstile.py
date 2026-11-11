"""Cloudflare Turnstile verification for the public auth routes.

Off unless ``TURNSTILE_SECRET_KEY`` is set: with no secret nothing is enforced
and Cloudflare is never called, so the code can ship before the keys exist.

Once on, it fails CLOSED: a missing token, a rejected token, a network error
and a Cloudflare outage all end in the same ``CaptchaRequiredError``. Failing
open would let an attacker switch the protection off by making the verify call
fail. Redirects are not followed and the secret never appears in a log line.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.core.errors import CaptchaRequiredError

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)
# Cloudflare documents a 2048-character ceiling for a token; anything longer is
# junk and is not worth a network call.
MAX_TOKEN_LENGTH = 2048


def enabled() -> bool:
    return bool(get_settings().turnstile_secret_key)


async def verify(token: str | None, *, ip: str | None = None) -> None:
    """Raise ``CaptchaRequiredError`` unless Cloudflare accepts the token.

    A no-op while the feature is off. Each token is single use on Cloudflare's
    side, so a replayed token is refused there, not here.
    """
    secret = get_settings().turnstile_secret_key
    if not secret:
        return
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise CaptchaRequiredError()
    data = {"secret": secret, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(VERIFY_URL, data=data)
        ok = resp.status_code == 200 and resp.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        # Outage or garbage from Cloudflare: refuse, never wave through.
        logger.warning("turnstile verify unavailable")
        raise CaptchaRequiredError() from None
    if not ok:
        raise CaptchaRequiredError()
