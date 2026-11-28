"""Whether this call may be recorded, decided before the first second of audio.

Recording is off unless the shop asked for it, and the two on-modes are not interchangeable: one
promises the caller a notice, the other demands a recorded consent. A missing policy is never read
as permission — the same mistake the AI provider policy used to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.platform.voice.domain.routing import RecordingMode

DEFAULT_RETENTION_DAYS: Final[int] = 30


@dataclass(frozen=True, slots=True)
class RecordingDecision:
    allowed: bool
    notice_required: bool
    consent_required: bool
    retention_days: int
    reason: str


def decide_recording(
    mode: RecordingMode | None,
    *,
    consent_captured: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> RecordingDecision:
    """Resolve one call's recording permission, defaulting to the protective answer."""
    if mode is None or mode is RecordingMode.OFF:
        return RecordingDecision(
            allowed=False,
            notice_required=False,
            consent_required=False,
            retention_days=retention_days,
            reason="this number does not record calls",
        )
    if mode is RecordingMode.WITH_NOTICE:
        return RecordingDecision(
            allowed=True,
            notice_required=True,
            consent_required=False,
            retention_days=retention_days,
            reason="recording with an announced notice",
        )
    if not consent_captured:
        return RecordingDecision(
            allowed=False,
            notice_required=True,
            consent_required=True,
            retention_days=retention_days,
            reason="this number records only after the caller consents",
        )
    return RecordingDecision(
        allowed=True,
        notice_required=True,
        consent_required=True,
        retention_days=retention_days,
        reason="recording consented by the caller",
    )
