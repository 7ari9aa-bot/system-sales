"""What a voice answer is made of, and what a provider must be able to do.

Two contracts live here because both exist to stop the same class of mistake: the model inventing
something the system never established.

``Fact`` is the only shape a merchant or customer number may travel in. It carries the currency,
the period, the shop's timezone, the moment it was read, whether the data was complete, and which
metric definition produced it. A number without those is not an answer, it is a guess with a
decimal point. The constructor refuses the three ways this goes wrong in practice: a value with no
currency, incomplete data presented as a number, and two currencies added together.

The provider protocols are deliberately thin and provider-neutral. LiveKit, OpenAI Realtime,
Gemini Live and a cascaded STT/LLM/TTS pipeline implement different subsets of the same ideas, so
capabilities are declared as data (``ProviderCapabilities``) and a router asks before it assumes
(invariant 9). Nothing in this module knows a vendor's name.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


class Completeness(enum.StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    STALE = "stale"


class ContractViolation(Exception):
    """An answer that would have to lie to be rendered."""


@dataclass(frozen=True, slots=True)
class Period:
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ContractViolation(f"period ends before it starts: {self.start}..{self.end}")

    def as_dict(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a number came from, so a wrong answer can be traced to a source, not a sentence."""

    source: str
    metric_definition_version: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source}
        if self.metric_definition_version:
            out["metric_definition_version"] = self.metric_definition_version
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True, slots=True)
class Fact:
    """One answered question about a shop, in a shape the agent cannot embellish.

    ``value`` is ``None`` when the system has no number to give. That is a first-class outcome:
    "no sales were recorded" and "we could not read the sales" are different sentences, and the
    second one is never rendered as ``0``.
    """

    metric: str
    value: Decimal | None
    currency: str | None
    period: Period | None
    timezone: str
    as_of: dt.datetime
    scope: str
    unit: str = "money"
    completeness: Completeness = Completeness.COMPLETE
    limitations: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.value is not None and self.unit == "money" and not self.currency:
            raise ContractViolation(
                f"{self.metric} has a value but no currency; an amount without a currency is a "
                "number, not money"
            )
        if self.value is not None and self.unit != "money" and self.currency:
            raise ContractViolation(f"{self.metric} is a {self.unit} and must not carry a currency")
        if self.value is None and self.completeness is Completeness.COMPLETE:
            raise ContractViolation(
                f"{self.metric} has no value and claims complete data; say why it is missing "
                "instead (limitations must name the gap)"
            )
        if self.value is None and not self.limitations:
            raise ContractViolation(f"{self.metric} has no value and no limitation explaining it")
        if self.as_of.tzinfo is None:
            raise ContractViolation(
                f"{self.metric} was read without a timezone; 'as of' must be an instant"
            )

    def as_dict(self) -> dict[str, Any]:
        """The wire shape: exactly the fields a screen or a spoken answer may use."""
        data: dict[str, Any] = {
            "metric": self.metric,
            "value": None if self.value is None else str(self.value),
            "currency": self.currency,
            "unit": self.unit,
            "period": None if self.period is None else self.period.as_dict(),
            **self.extra,
        }
        return {
            "status": "success" if self.value is not None else "unavailable",
            "data": data,
            "context": {
                "timezone": self.timezone,
                "as_of": self.as_of.isoformat(),
                "scope": self.scope,
            },
            "quality": {
                "completeness": self.completeness.value,
                "limitations": list(self.limitations),
            },
            "evidence": [item.as_dict() for item in self.evidence],
        }


def add_amounts(facts: list[Fact]) -> Fact:
    """Sum facts only when they are the same metric in the same currency over one period.

    This exists because "total revenue" is the single easiest number for an assistant to get
    wrong: two shops' currencies, or a partial day added to a full one, produce a total that looks
    authoritative and is false. Anything that does not line up raises instead of adding.
    """
    if not facts:
        raise ContractViolation("cannot add an empty set of facts")
    first = facts[0]
    if first.value is None:
        raise ContractViolation(f"{first.metric} has no value to add")
    for other in facts[1:]:
        if other.metric != first.metric:
            raise ContractViolation(
                f"refusing to add {first.metric} and {other.metric}: different metrics"
            )
        if other.currency != first.currency:
            raise ContractViolation(
                f"refusing to add {first.currency} and {other.currency}: different currencies"
            )
        if other.value is None:
            raise ContractViolation(f"{other.metric} has no value to add")
        if other.period != first.period:
            raise ContractViolation(f"refusing to add {other.metric} over a different period")
        if other.completeness is not Completeness.COMPLETE:
            raise ContractViolation(
                f"refusing to add {other.metric}: {other.completeness.value} data would be "
                "presented as a total"
            )
    total = sum((item.value for item in facts), start=Decimal("0"))
    return Fact(
        metric=first.metric,
        value=total,
        currency=first.currency,
        period=first.period,
        timezone=first.timezone,
        as_of=max(item.as_of for item in facts),
        scope=first.scope,
        completeness=Completeness.COMPLETE,
        limitations=(),
        evidence=tuple(ev for item in facts for ev in item.evidence),
    )


class AudioPath(enum.StrEnum):
    """Which of the three pipelines produced the voice, so a session can be judged per path."""

    SPEECH_TO_SPEECH = "speech_to_speech"
    CASCADED = "cascaded"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can actually do, declared rather than assumed.

    The router reads this before choosing a path. A provider that cannot interrupt cannot be put
    behind a barge-in experience, and a provider without an allowlisted policy cannot carry a
    confidential payload at all — that second rule is enforced in ``security/data_egress.py``.
    """

    name: str
    paths: frozenset[AudioPath]
    languages: frozenset[str]
    supports_barge_in: bool = False
    supports_streaming: bool = True
    supports_telephony: bool = False
    max_session_seconds: int | None = None

    def can_serve(self, path: AudioPath, language: str) -> bool:
        return path in self.paths and language.split("-")[0] in {
            item.split("-")[0] for item in self.languages
        }


@runtime_checkable
class RealtimeSpeechProvider(Protocol):
    """A live audio session with a model that hears and speaks."""

    async def create_session(self, config: dict[str, Any]) -> str: ...

    async def stream_audio(self, session_id: str, audio: bytes) -> None: ...

    async def interrupt(self, session_id: str) -> None: ...

    async def close_session(self, session_id: str) -> None: ...


@runtime_checkable
class STTProvider(Protocol):
    async def transcribe_stream(self, audio_stream: Any) -> Any: ...

    async def transcribe_file(self, audio_file: Any) -> str: ...


@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize_stream(self, text: str, voice_config: dict[str, Any]) -> Any: ...


@runtime_checkable
class TelephonyProvider(Protocol):
    async def accept_call(self, call_id: str) -> None: ...

    async def reject_call(self, call_id: str) -> None: ...

    async def transfer_call(self, call_id: str, destination: str) -> None: ...

    async def end_call(self, call_id: str) -> None: ...
