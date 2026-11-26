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
    "secret",
    "token",
)
_KEYS = "|".join(sorted(_SECRET_KEYS, key=len, reverse=True))

#: key=value or key: value (URL query, form body, repr of a dict, JSON).
_PAIR = re.compile(
    rf"(?P<key>(?<![A-Za-z0-9_])(?:{_KEYS}))(?P<sep>[\"']?\s*[=:]\s*[\"']?)(?P<val>[^&\s\"',}}\]\)]+)",
    re.IGNORECASE,
)
#: ``code`` is both an OAuth authorization code (a credential) and the field every
#: structured log line uses for an error or alert code. Blanket redaction hid the
#: one value an operator needs — ``platform.monitor_tripped code=[REDACTED]`` — so
#: only high-entropy values are rewritten: an authorization code is long, mixed
#: alphanumeric and has no underscore; an application code is a snake_case word.
_AUTH_CODE = re.compile(
    r"(?P<key>(?<![A-Za-z0-9_])code)(?P<sep>[\"']?\s*[=:]\s*[\"']?)"
    r"(?P<val>[A-Za-z0-9._~+/=\-]{16,})",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}")
#: A Meta token that shows up with no key in front of it.
_META_TOKEN = re.compile(r"\bEA[A-Za-z0-9]{20,}\b")


def _redact_authorization_code(match: re.Match[str]) -> str:
    """Redact ``code=`` only when the value is an OAuth code, not a log code."""
    value = match.group("val")
    looks_like_oauth = (
        "_" not in value
        and re.search(r"\d", value) is not None
        and re.search(r"[A-Za-z]", value) is not None
    )
    if looks_like_oauth:
        return f"{match.group('key')}{match.group('sep')}{REDACTED}"
    return match.group(0)


def redact(text: str) -> str:
    """``text`` with every credential value replaced by ``[REDACTED]``."""
    if not text:
        return text
    text = _PAIR.sub(lambda m: f"{m.group('key')}{m.group('sep')}{REDACTED}", text)
    text = _AUTH_CODE.sub(_redact_authorization_code, text)
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
