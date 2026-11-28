"""OPERATIONS request/response contracts.

Why this file exists
--------------------
Every endpoint in ``operations/router.py`` used to hand-build a ``dict`` and
declare no ``response_model``. Two costs, both paid by the caller:

* OpenAPI answered ``{}`` for the whole module, so a generated client had no
  type to hold and no field to be required about; and
* nothing checked the handler. A route that dropped a key — or grew one — was
  invisible until a screen rendered blank, because the only contract was
  prose in the function body.

The models below DESCRIBE the existing bodies; they do not reshape them. Every
field is named exactly as the route already spelled it, and the timestamp
fields are real ``datetime``\\ s so the wire format is the schema's business
rather than twenty call sites of ``.isoformat()``.

Request models moved here too, for the same reason: ``TaskCreate.due_date`` was
a free-form ``string`` that the route then discarded, and ``TaskUpdate``
carried an ``assignee_user_id`` nobody read and an unbounded ``priority``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# shared shapes
# --------------------------------------------------------------------------


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """Refuse a naive instant on the way IN.

    ``scheduled_jobs.run_at`` and ``tasks.due_date`` are ``TIMESTAMPTZ``. A
    naive value is resolved by Postgres against the SESSION timezone, so one
    body means a different instant depending on which pooler answered — a job
    an operator set for 09:00 can fire hours early. The alternative is to
    guess a zone here and be quietly wrong.
    """
    if value is not None and value.tzinfo is None:
        raise ValueError("a timezone offset is required (e.g. 2026-01-01T09:00:00+02:00)")
    return value


AwareDatetime = Annotated[dt.datetime, Field(description="timezone-aware ISO-8601")]


class TimestampedModel(BaseModel):
    """Base for reply models: the row's own columns, no ORM round-tripping."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# tasks (§83)
# --------------------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: uuid.UUID | None = None
    due_date: AwareDatetime | None = None
    # 1 high / 2 normal / 3 low. Bounded here rather than in the service so a
    # bad value is a 422 on the way in instead of a 400 from inside a flush.
    priority: int = Field(default=2, ge=1, le=3)

    @field_validator("due_date")
    @classmethod
    def _due_date_is_aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        return _aware(value)


class TaskUpdate(BaseModel):
    status: Annotated[str | None, Field(pattern="^(todo|in_progress|done|cancelled)$")] = None
    assignee_user_id: uuid.UUID | None = None
    priority: Annotated[int | None, Field(ge=1, le=3)] = None


class TaskSummary(TimestampedModel):
    """One row of ``GET /tasks`` — the inbox/list shape, not the full record."""

    id: uuid.UUID
    title: str
    status: str
    priority: int
    assignee_user_id: uuid.UUID | None
    due_date: dt.datetime | None
    source: str


class TaskMutationResult(BaseModel):
    """What a task write confirms: which row, and what state it is in now."""

    id: uuid.UUID
    status: str


# --------------------------------------------------------------------------
# search (§45)
# --------------------------------------------------------------------------


class SearchHit(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    title: str
    snippet: str | None


# --------------------------------------------------------------------------
# SLA (§46)
# --------------------------------------------------------------------------


class SLAPolicyUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    first_response_minutes: int = Field(gt=0, le=60 * 24 * 30)
    resolution_minutes: int = Field(gt=0, le=60 * 24 * 365)
    applies_to_channel: str | None = Field(default=None, max_length=31)
    is_default: bool = False


class SLAPolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    first_response_minutes: int
    resolution_minutes: int
    applies_to_channel: str | None
    is_default: bool
    status: str


class SLAPolicyList(BaseModel):
    items: list[SLAPolicyOut]


class BusinessCalendarUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Africa/Cairo", max_length=63)
    hours: dict[str, Any] = Field(default_factory=dict)
    holidays: list[Any] = Field(default_factory=list)
    is_default: bool = False


class BusinessCalendarOut(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    hours: dict[str, Any]
    holidays: list[Any]
    is_default: bool


class BusinessCalendarList(BaseModel):
    items: list[BusinessCalendarOut]


class SLARiskItem(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    kind: str
    status: str
    deadline_at: dt.datetime | None
    minutes_remaining: int | None
    at_risk: bool


class SLARiskList(BaseModel):
    items: list[SLARiskItem]
    # Which clock the deadlines were measured against — without it
    # ``minutes_remaining`` is a number the operator cannot interpret.
    timezone: str


# --------------------------------------------------------------------------
# SLO (§168)
# --------------------------------------------------------------------------


class AlertDestination(BaseModel):
    channel: str
    target: str


class SLODefinitionOut(BaseModel):
    name: str
    description: str
    target_percent: float
    window_hours: int
    warning_percent: float
    error_percent: float
    runbook: str
    alert_destinations: list[AlertDestination]


class SLODefinitionList(BaseModel):
    items: list[SLODefinitionOut]


class SLOMeasurement(BaseModel):
    name: str
    compliance_percent: float
    total: int
    met: int
    target_percent: float
    status: str
    window_since: str


class SLOMeasurementList(BaseModel):
    items: list[SLOMeasurement]


# --------------------------------------------------------------------------
# jobs (§84)
# --------------------------------------------------------------------------


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    last_error: str | None
    result: dict[str, Any] | None
    correlation_id: str | None
    actor_user_id: uuid.UUID | None
    created_at: dt.datetime | None
    updated_at: dt.datetime | None


class JobList(BaseModel):
    items: list[JobOut]


# --------------------------------------------------------------------------
# scheduled jobs (§154)
# --------------------------------------------------------------------------


class ScheduledJobReschedule(BaseModel):
    run_at: AwareDatetime

    @field_validator("run_at")
    @classmethod
    def _run_at_is_aware(cls, value: dt.datetime) -> dt.datetime:
        return _aware(value)


class ScheduledJobStatusResult(BaseModel):
    id: uuid.UUID
    status: str


class ScheduledJobRescheduleResult(BaseModel):
    id: uuid.UUID
    status: str
    run_at: dt.datetime | None


# --------------------------------------------------------------------------
# tenant fairness (§144)
# --------------------------------------------------------------------------


class FairnessBucket(BaseModel):
    limit: int
    current: int
    remaining: int
    percent_used: float


class FairnessCheckResult(BaseModel):
    resource: str
    limit: int
    current_usage: int
    remaining: int
    allowed: bool
