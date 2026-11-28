"""The Merchant Intelligence Gateway: the only way a voice agent reads a shop.

Four read paths, one shape. Operational questions ("where is order 4412?") read a record;
analytics questions read a metric from the registry; knowledge questions read the shop's own
documents; activity questions read the timeline. All four answer with a `Fact`, so a spoken answer
always carries currency, period, timezone, as-of, completeness and the definition that produced it.

Two rules this module exists to keep:

* The gateway calls domain readers. It never builds SQL, and the agent never sees a connection
  (invariant 4). A reader that cannot answer says so; it does not return zero.
* The persona is checked here as well as at the tool gateway, because a customer session must not
  reach merchant analytics even if a tool name were mis-registered (invariant 6).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.core.errors import PermissionDeniedError
from app.platform.voice.domain.contracts import (
    Completeness,
    Evidence,
    Fact,
    Period,
)
from app.platform.voice.domain.metrics import MetricDefinition, MetricUnit, metric
from app.platform.voice.domain.personas import PersonaType
from app.platform.voice.security.capabilities import SessionCapability


@dataclass(frozen=True, slots=True)
class Reading:
    """What a domain reader hands back, before it becomes a `Fact`."""

    value: Decimal | None
    currency: str | None = None
    completeness: Completeness = Completeness.COMPLETE
    limitations: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    extra: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def unavailable(cls, *inputs: str, reason: str | None = None) -> Reading:
        """The honest answer: no number, and the reason it is missing."""
        limitations = tuple(f"{name} unavailable" for name in inputs) or (
            reason or "the source could not be read",
        )
        return cls(
            value=None,
            completeness=Completeness.PARTIAL,
            limitations=limitations,
            missing_inputs=inputs,
        )


class AnalyticsReader(Protocol):
    async def read_metric(
        self,
        *,
        definition: MetricDefinition,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
        period: Period,
        currency: str,
    ) -> Reading: ...


class OperationalReader(Protocol):
    async def read_record(
        self,
        *,
        subject: str,
        reference: str,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
    ) -> Reading: ...


class KnowledgeReader(Protocol):
    async def search(self, *, question: str, tenant_id: uuid.UUID, limit: int) -> Reading: ...


class ActivityReader(Protocol):
    async def timeline(
        self,
        *,
        subject: str,
        reference: str,
        tenant_id: uuid.UUID,
        period: Period,
    ) -> Reading: ...


class MerchantIntelligenceGateway:
    """Read-only by construction: there is no method here that changes a shop."""

    def __init__(
        self,
        *,
        analytics: AnalyticsReader,
        operational: OperationalReader,
        knowledge: KnowledgeReader,
        activity: ActivityReader,
        currency: str = "EGP",
        timezone: str = "Africa/Cairo",
        clock: object | None = None,
    ) -> None:
        self._analytics = analytics
        self._operational = operational
        self._knowledge = knowledge
        self._activity = activity
        self._currency = currency
        self._timezone = timezone
        self._clock = clock

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _require_merchant(capability: SessionCapability) -> None:
        if capability.persona is not PersonaType.MERCHANT_ASSISTANT:
            raise PermissionDeniedError(
                "merchant intelligence is not available to a customer session"
            )

    @staticmethod
    def _require_scope(capability: SessionCapability, scope: str) -> None:
        if scope not in capability.scopes:
            raise PermissionDeniedError(f"this session does not hold {scope}")

    def _now(self) -> dt.datetime:
        if self._clock is not None:
            return self._clock()  # type: ignore[operator]
        return dt.datetime.now(dt.UTC)

    # ------------------------------------------------------------ four paths

    async def metric(
        self,
        capability: SessionCapability,
        code: str,
        *,
        period: Period,
        scope: str = "all_locations",
    ) -> Fact:
        """One registry metric, with its definition attached."""
        self._require_merchant(capability)
        definition = metric(code)
        self._require_scope(capability, definition.scope)
        reading = await self._analytics.read_metric(
            definition=definition,
            tenant_id=capability.tenant_id,
            workspace_id=capability.workspace_id,
            period=period,
            currency=self._currency,
        )
        return self._fact(definition, reading, period=period, scope=scope)

    async def operational(
        self, capability: SessionCapability, *, subject: str, reference: str
    ) -> Fact:
        """A record the owner asked about by name: an order, a shipment, a product."""
        self._require_merchant(capability)
        self._require_scope(capability, "orders:read")
        reading = await self._operational.read_record(
            subject=subject,
            reference=reference,
            tenant_id=capability.tenant_id,
            workspace_id=capability.workspace_id,
        )
        return self._fact(
            MetricDefinition(
                code=f"{subject}.record",
                label=f"{subject} record",
                label_ar=f"سجل {subject}",
                unit=_unit_for(subject),
                scope="orders:read",
                formula=f"the {subject} row identified by {reference}",
                needs=(subject,),
            ),
            reading,
            period=None,
            scope=reference,
        )

    async def knowledge(
        self, capability: SessionCapability, *, question: str, limit: int = 5
    ) -> Fact:
        """The shop's own documents. Retrieval answers wording, never a live number."""
        self._require_merchant(capability)
        reading = await self._knowledge.search(
            question=question, tenant_id=capability.tenant_id, limit=limit
        )
        return self._fact(
            MetricDefinition(
                code="knowledge.answer",
                label="Shop knowledge",
                label_ar="معلومات المتجر",
                unit=_unit_for("knowledge"),
                scope="catalog:read",
                formula="retrieval over the shop's own documents",
                needs=("documents",),
            ),
            reading,
            period=None,
            scope="knowledge",
        )

    async def activity(
        self,
        capability: SessionCapability,
        *,
        subject: str,
        reference: str,
        period: Period,
    ) -> Fact:
        """What happened to this thing, in order, from the event history."""
        self._require_merchant(capability)
        reading = await self._activity.timeline(
            subject=subject, reference=reference, tenant_id=capability.tenant_id, period=period
        )
        return self._fact(
            MetricDefinition(
                code=f"{subject}.timeline",
                label=f"{subject} history",
                label_ar=f"سجل {subject}",
                unit=_unit_for("timeline"),
                scope="orders:read",
                formula=f"events touching {subject} {reference} inside the period",
                needs=("events",),
            ),
            reading,
            period=period,
            scope=reference,
        )

    async def summary(self, capability: SessionCapability, *, period: Period) -> tuple[Fact, ...]:
        """The progressive first step: headline numbers only, no per-record detail.

        A caller that needs more asks a second question; the gateway never ships the shop to the
        model to save a round trip.
        """
        self._require_merchant(capability)
        headline = ("net_sales", "order_count", "aov")
        facts: list[Fact] = []
        for code in headline:
            definition = metric(code)
            if definition.scope not in capability.scopes:
                continue
            facts.append(await self.metric(capability, code, period=period))
        return tuple(facts)

    # ------------------------------------------------------------- assembly

    def _fact(
        self,
        definition: MetricDefinition,
        reading: Reading,
        *,
        period: Period | None,
        scope: str,
    ) -> Fact:
        completeness = reading.completeness
        limitations = list(reading.limitations)
        for missing in reading.missing_inputs:
            note = f"{missing} was not available, so {definition.label} is not computed"
            if note not in limitations:
                limitations.append(note)
        value = reading.value
        unit = definition.unit.value
        currency = (
            None
            if definition.unit is not MetricUnit.MONEY
            else (reading.currency or self._currency)
        )
        if value is not None and reading.missing_inputs:
            value = None
            completeness = Completeness.PARTIAL
        return Fact(
            metric=definition.code,
            value=value,
            currency=currency,
            unit=unit,
            period=period,
            timezone=self._timezone,
            as_of=self._now(),
            scope=scope,
            completeness=completeness,
            limitations=tuple(limitations),
            evidence=(definition.evidence(), *reading.evidence),
            extra=dict(reading.extra),
        )


def _unit_for(subject: str) -> MetricUnit:
    """A record or a timeline is a count of things; money never enters these two paths."""
    return MetricUnit.COUNT
