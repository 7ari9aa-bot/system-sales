"""Keep credentials out of the logs.

``httpx`` logs every request at INFO with the full URL, and Meta's Graph API takes its
tokens in the query string, so ``access_token=EAA...`` ended up in the platform logs.
The filter below rewrites the *formatted* message of every record, so it covers any
library that logs a URL or a header, not just ``httpx``.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[REDACTED]"

#: Query/form/JSON parameters whose value is a credential.
_SECRET_KEYS = (
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "app_secret",
    "fb_exchange_token",
    "input_token",
    "appsecret_proof",
    "api_key",
    "apikey",
    "password",
    "code",
    "secret",
    "token",
)
_KEYS = "|".join(sorted(_SECRET_KEYS, key=len, reverse=True))

#: key=value or key: value (URL query, form body, repr of a dict, JSON).
_PAIR = re.compile(
    rf"(?P<key>(?<![A-Za-z0-9_])(?:{_KEYS}))(?P<sep>[\"']?\s*[=:]\s*[\"']?)(?P<val>[^&\s\"',}}\]\)]+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}")
#: A Meta token that shows up with no key in front of it.
_META_TOKEN = re.compile(r"\bEA[A-Za-z0-9]{20,}\b")


def redact(text: str) -> str:
    """``text`` with every credential value replaced by ``[REDACTED]``."""
    if not text:
        return text
    text = _PAIR.sub(lambda m: f"{m.group('key')}{m.group('sep')}{REDACTED}", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    return _META_TOKEN.sub(REDACTED, text)


class RedactSecretsFilter(logging.Filter):
    """Rewrites a record's message in place; never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not lose the line
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def install_secret_redaction() -> None:
    """Attach the filter to every root handler and quieten the HTTP client loggers.

    A filter on a *handler* sees records from every logger; one on the root logger would
    miss records propagated from child loggers. Idempotent.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
            handler.addFilter(RedactSecretsFilter())
    # Second layer: the per-request URL lines carry no information worth a token's risk.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
