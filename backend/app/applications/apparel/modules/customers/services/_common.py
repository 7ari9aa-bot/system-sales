"""Common constants, issue identifiers, and normalization helpers for customer services."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.contact_norm import ContactNormalizationError

_RESOLVE_ATTEMPTS = 2
# The extra key migration d5a1c7e94b02 leaves its contact findings under.
_BACKFILL_KEY = "m12_contact_backfill"

# The two things the backfill could not decide, named once here and used by
# both the queue (``contact_data_quality_report``) and its resolve half, so
# the vocabulary the operator sees and the vocabulary the server checks can
# never drift. Each issue owns exactly the mark keys its resolution may clear.
ISSUE_LEGACY_DEFAULT = "phone_legacy_default_country"
ISSUE_CANONICAL_COLLISION = "phone_canonical_collision"
_ISSUE_MARK_KEYS: dict[str, tuple[str, ...]] = {
    ISSUE_LEGACY_DEFAULT: ("phone_status", "legacy_raw", "suspected_phone"),
    ISSUE_CANONICAL_COLLISION: ("phone_collision",),
}
# A ``+9640`` fabrication resolves two ways (the column is right after all, or
# the operator states the real number). A collision resolves ONE way: the two
# rows are confirmed different people. Merging them is NOT offered here —
# see ``resolve_contact_issue``.
_ISSUE_RESOLUTIONS: dict[str, tuple[str, ...]] = {
    ISSUE_LEGACY_DEFAULT: ("confirm_genuine", "correct"),
    ISSUE_CANONICAL_COLLISION: ("confirm_distinct",),
}


def _contact_flag(extra: dict | None) -> dict:
    """The backfill mark on a row's ``extra``, as a dict (possibly empty)."""
    flag = ((extra or {}).get("data_quality") or {}).get(_BACKFILL_KEY)
    return flag if isinstance(flag, dict) else {}


def _open_contact_issues(flag: dict) -> list[str]:
    """Which of the two queue issues this mark still has open.

    Read off the MARK, not a re-scan — same rule the queue list uses: a row
    the backfill merely rewrote carries provenance (``phone_from``) with
    nothing to act on.
    """
    issues: list[str] = []
    if flag.get("phone_status") == "needs_review":
        issues.append(ISSUE_LEGACY_DEFAULT)
    if flag.get("phone_collision"):
        issues.append(ISSUE_CANONICAL_COLLISION)
    return issues


def _canonical_or_raw(raw: str | None, normalize) -> str | None:
    """Canonical form when we are confident, otherwise the value as it came in.

    Deliberately tolerant because this is the channel/webhook entry: raising a
    400 there makes the provider retry the delivery forever. An unparseable
    value is stored UNCHANGED — never as a fabricated ``+…`` — and then matches
    as itself, exactly as before the normalization layer. The human write path
    (`update_customer`) is strict instead, because there a typo is the caller's
    to fix.
    """
    if not raw or not raw.strip():
        return None
    try:
        return normalize(raw)
    except ContactNormalizationError:
        return raw.strip()


def _now() -> datetime:
    return datetime.now(UTC)
