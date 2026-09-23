"""Spec §144 — Tenant fairness budgets.

Rate limiting (middleware.py) protects the API from request flooding. Tenant
fairness budgets protect the PLATFORM from a single tenant exhausting shared
resources:

- AI token consumption (a single tenant's AI runs should not consume 90%
  of the daily token pool)
- Message volume (a tenant sending 100k messages/day should not saturate
  the outbound queue)
- Storage consumption (a tenant's media attachments should not fill the
  S3 bucket)
- Worker concurrency (a tenant's long-running jobs should not occupy all
  workers)

Each budget is enforced at the point of consumption, not at the API edge.
The edge rate limiter is about REQUESTS; the fairness budget is about
RESOURCE UNITS.

This service provides:
- `check_budget()`: check if a tenant has remaining budget for a resource
  type. Returns the remaining units or 0 if exhausted.
- `consume()`: deduct units from a tenant's budget. Called by the
  consumer (AI gateway, message worker, etc.).
- `refund()`: return units to the budget (e.g., a failed AI run refunds
  its reserved tokens).
- `get_usage()`: return the current usage snapshot for a tenant.

The budgets are stored in Redis as sliding-window counters (like the edge
rate limiter) so they are atomic and fast. If Redis is unavailable, the
check fails OPEN (the request proceeds) — fairness is best-effort, not a
hard gate. A hard gate would take the whole platform down when Redis is
unavailable, which is worse than one tenant briefly exceeding its budget.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


class ResourceType(StrEnum):
    """The shared resources a tenant can consume."""

    AI_TOKENS = "ai_tokens"
    MESSAGES_OUTBOUND = "messages_outbound"
    STORAGE_BYTES = "storage_bytes"
    WORKER_SECONDS = "worker_seconds"


# §144: the priority order is fixed by the spec —
#   Human Response > AI Response > Critical System Events >
#   Customer Webhooks > Normal Automation > Bulk / Campaign Work
# A big campaign (BULK_CAMPAIGN) may never starve a customer conversation
# (rank 1-2). Streams are per-aggregate, so the tier is not a reordering
# inside one queue: it tells the CONSUMER side what may be throttled and
# what may not (CampaignWorker paces; MessageWorker never does), and gives
# the scheduler a total order for picking which bulk work runs next.
class EventPriority(StrEnum):
    HUMAN_RESPONSE = "human_response"
    AI_RESPONSE = "ai_response"
    CRITICAL_SYSTEM = "critical_system"
    CUSTOMER_WEBHOOK = "customer_webhook"
    NORMAL_AUTOMATION = "normal_automation"
    BULK_CAMPAIGN = "bulk_campaign"

    @property
    def rank(self) -> int:
        """1 = most urgent (§144 order), 6 = lowest."""
        return _PRIORITY_RANKS[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, EventPriority):
            return NotImplemented
        return self.rank < other.rank


_PRIORITY_RANKS: dict[EventPriority, int] = {
    priority: rank
    for rank, priority in enumerate(
        (
            EventPriority.HUMAN_RESPONSE,
            EventPriority.AI_RESPONSE,
            EventPriority.CRITICAL_SYSTEM,
            EventPriority.CUSTOMER_WEBHOOK,
            EventPriority.NORMAL_AUTOMATION,
            EventPriority.BULK_CAMPAIGN,
        ),
        start=1,
    )
}

# Every real DOMAIN_EVENT_TYPES entry (minus test fixtures) names its tier —
# the mapping is over event types the outbox actually publishes.
DOMAIN_PRIORITIES: dict[str, EventPriority] = {
    # Human Response: staff-initiated outbound is the thing fairness must
    # never delay behind bulk work.
    "message.outbound": EventPriority.HUMAN_RESPONSE,
    # AI Response: inbound customer messages drive the AI reply path.
    "message.received": EventPriority.AI_RESPONSE,
    # Critical system: money, privacy, security and restore lifecycle events.
    "order.created": EventPriority.CRITICAL_SYSTEM,
    "order.status_changed": EventPriority.CRITICAL_SYSTEM,
    "order.cancelled": EventPriority.CRITICAL_SYSTEM,
    "order.refunded": EventPriority.CRITICAL_SYSTEM,
    "order.shipping_updated": EventPriority.CRITICAL_SYSTEM,
    "privacy.customer_deleted": EventPriority.CRITICAL_SYSTEM,
    "privacy.customer_purge_required": EventPriority.CRITICAL_SYSTEM,
    "platform.secret_rotated": EventPriority.CRITICAL_SYSTEM,
    "tenant.restore.requested": EventPriority.CRITICAL_SYSTEM,
    "tenant.restore.completed": EventPriority.CRITICAL_SYSTEM,
    "ai.canary_started": EventPriority.CRITICAL_SYSTEM,
    "ai.canary_rolled_back": EventPriority.CRITICAL_SYSTEM,
    # Customer Webhooks: provider deliveries (§22 ingress, §24 replay,
    # outbound deliveries) outrank automation but not interactive paths.
    "webhook.ingest": EventPriority.CUSTOMER_WEBHOOK,
    "webhook.event.retry": EventPriority.CUSTOMER_WEBHOOK,
    "webhook.deliver": EventPriority.CUSTOMER_WEBHOOK,
    # Normal Automation: orchestration and housekeeping events.
    "notification.queued": EventPriority.NORMAL_AUTOMATION,
    "customer.merged": EventPriority.NORMAL_AUTOMATION,
    "saga.started": EventPriority.NORMAL_AUTOMATION,
    "saga.completed": EventPriority.NORMAL_AUTOMATION,
    "saga.failed": EventPriority.NORMAL_AUTOMATION,
    "journey.run.started": EventPriority.NORMAL_AUTOMATION,
    "journey.run.completed": EventPriority.NORMAL_AUTOMATION,
    "automation.service_token.issued": EventPriority.NORMAL_AUTOMATION,
    "automation.service_token.revoked": EventPriority.NORMAL_AUTOMATION,
    # Bulk / Campaign: the throttled tier.
    "campaign.run.started": EventPriority.BULK_CAMPAIGN,
    "campaign.run.batch": EventPriority.BULK_CAMPAIGN,
    "campaign.run.completed": EventPriority.BULK_CAMPAIGN,
}


def priority_for(event_type: str) -> EventPriority:
    """The §144 tier of one event type; unknown future types land on the
    automation tier — never more urgent than the spec says."""
    return DOMAIN_PRIORITIES.get(event_type, EventPriority.NORMAL_AUTOMATION)


# Per-tenant daily budgets. These are deployment-wide defaults; a per-tenant
# override would be a database column (tenant_fairness_budgets table) in a
# future task. The values are intentionally generous for a single tenant but
# tight enough that 10 tenants all maxing out would still leave capacity.
DEFAULT_DAILY_BUDGETS: dict[ResourceType, int] = {
    ResourceType.AI_TOKENS: 2_000_000,  # 2M tokens/day per tenant
    ResourceType.MESSAGES_OUTBOUND: 10_000,  # 10k outbound messages/day
    ResourceType.STORAGE_BYTES: 5_368_709_120,  # 5 GiB/day of media uploads
    ResourceType.WORKER_SECONDS: 3_600,  # 1 hour of worker time/day
}

# Redis key prefix for fairness budgets
_KEY_PREFIX = "fairness"
# Sliding window: 24 hours
_WINDOW_SECONDS = 86400


def _budget_key(tenant_id: uuid.UUID, resource: ResourceType) -> str:
    """Redis key for a tenant's resource budget counter."""
    return f"{_KEY_PREFIX}:{resource.value}:{tenant_id}"


@dataclass(slots=True, frozen=True)
class BudgetCheck:
    """The result of a budget check."""

    resource: ResourceType
    limit: int
    current_usage: int
    remaining: int
    allowed: bool


async def check_budget(
    tenant_id: uuid.UUID,
    resource: ResourceType,
    *,
    units: int = 1,
) -> BudgetCheck:
    """§144: check if the tenant has `units` remaining in its budget.

    This does NOT consume — it is a pre-flight check. Call `consume()` to
    actually deduct. The check is approximate (it reads the current counter
    without consuming) so a race between check and consume is possible.
    """
    limit = DEFAULT_DAILY_BUDGETS[resource]
    try:
        redis = get_redis()
        key = _budget_key(tenant_id, resource)
        current = int(await redis.get(key) or 0)
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning(
            "fairness.check_failed tenant=%s resource=%s error=%s — failing open",
            tenant_id,
            resource.value,
            type(exc).__name__,
        )
        return BudgetCheck(
            resource=resource,
            limit=limit,
            current_usage=0,
            remaining=limit,
            allowed=True,
        )
    remaining = max(limit - current, 0)
    return BudgetCheck(
        resource=resource,
        limit=limit,
        current_usage=current,
        remaining=remaining,
        allowed=remaining >= units,
    )


async def consume(
    tenant_id: uuid.UUID,
    resource: ResourceType,
    *,
    units: int = 1,
) -> bool:
    """§144: deduct `units` from the tenant's budget. Returns True if allowed.

    Atomic: the increment and the TTL are set in a single pipeline. If the
    tenant exceeds the budget, the units are still consumed (the counter
    goes above the limit) but the function returns False so the caller can
    refuse the operation.
    """
    try:
        redis = get_redis()
        key = _budget_key(tenant_id, resource)
        pipe = redis.pipeline()
        pipe.incrby(key, units)
        pipe.expire(key, _WINDOW_SECONDS)
        results = await pipe.execute()
        new_total = int(results[0] or 0)
        limit = DEFAULT_DAILY_BUDGETS[resource]
        return new_total <= limit
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning(
            "fairness.consume_failed tenant=%s resource=%s error=%s — failing open",
            tenant_id,
            resource.value,
            type(exc).__name__,
        )
        return True


async def refund(
    tenant_id: uuid.UUID,
    resource: ResourceType,
    *,
    units: int = 1,
) -> None:
    """§144: return units to the tenant's budget (e.g., a failed AI run).

    This decrements the counter. If the counter would go below 0, it is
    clamped at 0 (a refund of 1000 tokens on a counter of 500 does not
    make the counter -500).
    """
    try:
        redis = get_redis()
        key = _budget_key(tenant_id, resource)
        # DECRBY but don't go below 0
        current = int(await redis.get(key) or 0)
        new_val = max(current - units, 0)
        await redis.set(key, new_val, ex=_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "fairness.refund_failed tenant=%s resource=%s error=%s",
            tenant_id,
            resource.value,
            type(exc).__name__,
        )


async def get_usage(tenant_id: uuid.UUID) -> dict:
    """§144: return the current usage snapshot for all resources."""
    result: dict[str, dict] = {}
    for resource in ResourceType:
        limit = DEFAULT_DAILY_BUDGETS[resource]
        try:
            redis = get_redis()
            key = _budget_key(tenant_id, resource)
            current = int(await redis.get(key) or 0)
        except Exception:  # noqa: BLE001
            current = 0
        result[resource.value] = {
            "limit": limit,
            "current": current,
            "remaining": max(limit - current, 0),
            "percent_used": round(current / limit * 100, 2) if limit > 0 else 0,
        }
    return result


__all__ = [
    "BudgetCheck",
    "DEFAULT_DAILY_BUDGETS",
    "DOMAIN_PRIORITIES",
    "EventPriority",
    "ResourceType",
    "check_budget",
    "consume",
    "get_usage",
    "priority_for",
    "refund",
]
