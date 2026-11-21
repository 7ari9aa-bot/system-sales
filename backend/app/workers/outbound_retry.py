"""Which refused sends may be tried again on their own, and when.

A send ends in one of three ways (see ``message_worker``): SENT, FAILED (the provider answered and
refused) or UNKNOWN (no answer, so the message may have arrived). Only the middle one is ever
retried here, and only when Meta's own error code says the refusal is temporary:

* UNKNOWN is never retried. The request may have reached the customer, so a second send could
  deliver the same message twice. That rule is older than this module and is not touched.
* A refusal whose code is not in ``TRANSIENT_GRAPH_CODES`` is treated as final, exactly as before.
  The table is deliberately short and only holds codes Meta documents as temporary: guessing from
  free text would retry refusals that can never succeed (a closed 24-hour window, a dead token)
  and could resend a message that did arrive.
* The 24-hour window and the channel policy are checked again on every attempt by
  ``_deliver_one``, so a retry that waited past the window fails instead of being sent.
"""

from __future__ import annotations

import re

# Meta Graph API error reference. Rate limits and "try again later" only; nothing about
# permissions, tokens, recipients or content.
TRANSIENT_GRAPH_CODES: frozenset[int] = frozenset(
    {
        1,  # unknown error, "please retry your request later"
        2,  # service temporarily unavailable
        4,  # application request limit reached
        17,  # user request limit reached
        32,  # page request limit reached
        613,  # calls to this API have exceeded the rate limit
        80007,  # rate limit (WhatsApp Business management)
        130429,  # WhatsApp Cloud API throughput reached
        131056,  # WhatsApp pair rate limit (too many messages to one number)
    }
)

# Seconds to wait before attempt 2, 3 and 4. After the last one the message fails for good.
RETRY_DELAYS_SECONDS: tuple[int, ...] = (60, 300, 1800)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_CODE = re.compile(r"""['"]code['"]\s*:\s*(\d+)""")
_HASH_CODE = re.compile(r"\(#(\d+)\)")


def graph_error_code(error_text: str | None) -> int | None:
    """The Graph error ``code`` quoted in a provider error message, if there is exactly one.

    Adapters raise ``... HTTP 429 - {"error": {"code": 130429, ...}}``. Only a numeric ``code``
    key inside that quoted body counts; prose that merely mentions a number does not.
    """
    if not error_text:
        return None
    found: set[int] = set()
    for blob in _JSON_OBJECT.findall(error_text):
        found.update(int(m) for m in _CODE.findall(blob))
    found.update(int(m) for m in _HASH_CODE.findall(error_text))
    return found.pop() if len(found) == 1 else None


def is_transient_refusal(error_text: str | None) -> bool:
    """True only when the provider refused the send AND its code says to try again later."""
    code = graph_error_code(error_text)
    return code is not None and code in TRANSIENT_GRAPH_CODES


def next_retry_delay(failed_attempts: int) -> int | None:
    """Seconds to wait after ``failed_attempts`` refusals, or None once the budget is spent."""
    if failed_attempts < 1 or failed_attempts > len(RETRY_DELAYS_SECONDS):
        return None
    return RETRY_DELAYS_SECONDS[failed_attempts - 1]
