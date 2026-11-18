"""What Instagram accepts and what its errors mean — one place, no network.

Everything here is taken from Meta's Instagram Platform pages (Send Messages, updated
28 Sep 2026; Instagram Platform error codes, updated 2 Jun 2026) and kept as plain data
and pure functions so each rule can be tested without a Graph call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The Graph version lives in `app/core/instagram_version.py`, shared with account verification.

# ---------------------------------------------------------------- message limits

#: A text message is UTF-8 and at most 1000 BYTES (not characters): Arabic letters take two
#: bytes each, so about 500 of them fit. Meta refuses a longer message outright.
MAX_TEXT_BYTES = 1000

#: Quick replies: at most 13 plain-text buttons, each cut at 20 characters.
MAX_QUICK_REPLIES = 13
QUICK_REPLY_TITLE_CHARS = 20

#: At most ten images may travel in one message.
MAX_IMAGES_PER_MESSAGE = 10


@dataclass(frozen=True, slots=True)
class MediaRule:
    kind: str  # the Send API attachment type
    extensions: frozenset[str]
    max_bytes: int


_MB = 1024 * 1024

#: Supported formats and size caps, per attachment type, as Meta documents them.
MEDIA_RULES: dict[str, MediaRule] = {
    "image": MediaRule("image", frozenset({"png", "jpg", "jpeg"}), 8 * _MB),
    "audio": MediaRule("audio", frozenset({"aac", "m4a", "wav", "mp4"}), 25 * _MB),
    "video": MediaRule("video", frozenset({"mp4", "ogg", "avi", "mov", "webm"}), 25 * _MB),
    "file": MediaRule("file", frozenset({"pdf"}), 25 * _MB),
}

# What the inbox calls a kind of media -> what the Send API calls it.
_KIND_ALIASES = {
    "image": "image",
    "photo": "image",
    "audio": "audio",
    "voice": "audio",
    "video": "video",
    "file": "file",
    "document": "file",
}


class InstagramLimitError(ValueError):
    """The message breaks a rule Instagram would refuse it for. Caught before any call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def text_bytes(text: str | None) -> int:
    return len((text or "").encode("utf-8"))


def check_text(text: str | None) -> None:
    size = text_bytes(text)
    if size > MAX_TEXT_BYTES:
        raise InstagramLimitError(
            "text_too_long",
            f"an Instagram message is at most {MAX_TEXT_BYTES} bytes "
            f"(about {MAX_TEXT_BYTES // 2} Arabic letters); this one is {size}",
        )


def media_kind(raw: str | None) -> str:
    """The Send API attachment type for what the inbox calls this media."""
    return _KIND_ALIASES.get(str(raw or "image").lower(), "image")


def _extension(url: str) -> str:
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    return path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""


def check_media(url: str, kind: str, size_bytes: int | None = None) -> None:
    """Refuse a format or size Instagram would refuse. Size is checked only when known."""
    rule = MEDIA_RULES.get(kind)
    if rule is None:
        raise InstagramLimitError("media_kind", f"Instagram cannot send {kind!r} attachments")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise InstagramLimitError("media_url", "the attachment must be a public https link")
    ext = _extension(url)
    # A signed storage link may carry no extension at all; only a KNOWN wrong one is refused.
    if ext and ext not in rule.extensions:
        allowed = ", ".join(sorted(rule.extensions))
        raise InstagramLimitError(
            "media_format", f"Instagram accepts only {allowed} for {kind}; this is .{ext}"
        )
    if size_bytes is not None and size_bytes > rule.max_bytes:
        raise InstagramLimitError(
            "media_size",
            f"a {kind} is at most {rule.max_bytes // _MB} MB; this one is "
            f"{size_bytes / _MB:.1f} MB",
        )


# ------------------------------------------------------------- error classification

#: What the caller should do about a failure.
RETRY = "retry"  # transient: try again later, the message is not lost
RECONNECT = "reconnect"  # the token is dead: the merchant must reconnect the account
PERMISSION = "permission"  # the app lacks a permission or access level
WINDOW = "window"  # outside the messaging window: a human-agent reply or a template is needed
RECIPIENT = "recipient"  # the recipient cannot be messaged (wrong id, blocked, not signed in)
CONTENT = "content"  # this content is refused: change it, do not retry
LIMIT = "limit"  # a daily or rate limit: wait, do not retry now
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InstagramFailure:
    kind: str
    retryable: bool
    code: int | None
    subcode: int | None
    #: A short sentence the inbox can show an agent, in Arabic.
    message_ar: str


_SUBCODES: dict[int, tuple[str, bool, str]] = {
    # Publishing (Instagram Platform error codes)
    2207042: (LIMIT, False, "وصل الحساب للحد اليومي للنشر. جرّب بكرة."),
    2207051: (CONTENT, False, "إنستجرام رفض النشر لأنه شاكك إنه سبام."),
    2207050: (RECONNECT, False, "حساب إنستجرام مقيّد أو محتاج تسجيل دخول من التطبيق."),
    2207004: (CONTENT, False, "الصورة أكبر من 8 ميجا."),
    2207005: (CONTENT, False, "صيغة الصورة مش مدعومة. استخدم JPEG."),
    2207009: (CONTENT, False, "نسبة أبعاد الصورة مش مقبولة (من 4:5 لـ 1.91:1)."),
    2207010: (CONTENT, False, "الكابشن أطول من 2200 حرف."),
    2207028: (CONTENT, False, "الألبوم لازم يكون من 2 لـ 10 صور."),
    2207052: (CONTENT, False, "إنستجرام مقدرش يحمّل الصورة من الرابط."),
    2207003: (RETRY, True, "تحميل الصورة أخد وقت طويل. حاول تاني."),
    2207001: (RETRY, True, "مشكلة مؤقتة عند إنستجرام. حاول تاني."),
    2207032: (RETRY, True, "فشل تجهيز المنشور. حاول تاني."),
    2207020: (RETRY, True, "انتهت صلاحية الوسائط. ارفعها من جديد."),
    # Messaging
    2534014: (RECIPIENT, False, "العميل ده مش موجود أو الـ ID غلط."),
    2534022: (WINDOW, False, "خارج نافذة الرد. مينفعش نبعت رسالة عادية دلوقتي."),
    2534066: (WINDOW, False, "خارج نافذة الرد المسموحة."),
}

_CODES: dict[int, tuple[str, bool, str]] = {
    190: (RECONNECT, False, "التوكن انتهى أو اتلغى. اربط حساب إنستجرام من جديد."),
    102: (RECONNECT, False, "الجلسة انتهت. اربط حساب إنستجرام من جديد."),
    10: (PERMISSION, False, "التطبيق ناقصه صلاحية. راجع صلاحيات إنستجرام."),
    200: (PERMISSION, False, "التطبيق ناقصه صلاحية. راجع صلاحيات إنستجرام."),
    299: (PERMISSION, False, "التطبيق ناقصه صلاحية. راجع صلاحيات إنستجرام."),
    4: (LIMIT, True, "إنستجرام وصل لحد الطلبات. هنحاول تاني بعد شوية."),
    17: (LIMIT, True, "إنستجرام وصل لحد الطلبات. هنحاول تاني بعد شوية."),
    32: (LIMIT, True, "إنستجرام وصل لحد الطلبات. هنحاول تاني بعد شوية."),
    613: (LIMIT, True, "إنستجرام وصل لحد الطلبات. هنحاول تاني بعد شوية."),
    368: (CONTENT, False, "إنستجرام منع الإرسال مؤقتًا لمخالفة السياسات."),
    551: (RECIPIENT, False, "العميل مش متاح للرسائل دلوقتي."),
    1: (RETRY, True, "مشكلة مؤقتة عند إنستجرام. حاول تاني."),
    2: (RETRY, True, "إنستجرام مش متاح مؤقتًا. حاول تاني."),
}

_ERROR_JSON = re.compile(r"\{.*\}", re.DOTALL)
_CODE_IN_TEXT = re.compile(r"""['"]?code['"]?\s*[:=]\s*(\d+)""")
_SUBCODE_IN_TEXT = re.compile(r"""['"]?error_subcode['"]?\s*[:=]\s*(\d+)""")
_HASH_CODE = re.compile(r"\(#(\d+)\)")
_HTTP_IN_TEXT = re.compile(r"HTTP\s+(\d{3})")


def _numbers(error: Any, text: str) -> tuple[int | None, int | None]:
    code = subcode = None
    if isinstance(error, dict):
        code, subcode = error.get("code"), error.get("error_subcode")
    if code is None:
        m = _CODE_IN_TEXT.search(text) or _HASH_CODE.search(text)
        code = int(m.group(1)) if m else None
    if subcode is None:
        m = _SUBCODE_IN_TEXT.search(text)
        subcode = int(m.group(1)) if m else None
    try:
        return (
            int(code) if code is not None else None,
            int(subcode) if subcode is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def classify_instagram_error(error: Any) -> InstagramFailure:
    """Read a Graph error (a dict, an exception, or its text) and say what to do about it.

    The subcode is the more specific signal, so it wins; the bare code is the fallback;
    a bare HTTP status is the last resort, and anything unrecognised stays UNKNOWN
    (and not retryable) rather than being guessed at.
    """
    text = str(error)
    body = error.get("error", error) if isinstance(error, dict) else None
    code, subcode = _numbers(body, text)

    if subcode in _SUBCODES:
        kind, retryable, message = _SUBCODES[subcode]
        return InstagramFailure(kind, retryable, code, subcode, message)
    if code in _CODES:
        kind, retryable, message = _CODES[code]
        return InstagramFailure(kind, retryable, code, subcode, message)

    http = _HTTP_IN_TEXT.search(text)
    status = int(http.group(1)) if http else None
    if status == 429:
        kind, retryable, message = _CODES[4]
        return InstagramFailure(kind, retryable, code, subcode, message)
    if status is not None and status >= 500:
        return InstagramFailure(RETRY, True, code, subcode, "مشكلة مؤقتة عند إنستجرام. حاول تاني.")
    return InstagramFailure(UNKNOWN, False, code, subcode, "إنستجرام رفض الرسالة لسبب غير معروف.")
