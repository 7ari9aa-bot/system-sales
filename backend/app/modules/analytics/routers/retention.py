"""§55-57 retention policy routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import ValidationError
from app.modules.analytics import retention, schemas

from ._deps import AnalyticsReadCtx, AnalyticsWriteCtx, router


async def _write_audit_row(*args, **kwargs):
    from app.modules.analytics import router as analytics_router
    return await analytics_router.write_audit_row(*args, **kwargs)


class RetentionPolicyChoice(BaseModel):
    """Body of ``PUT /analytics/retention/policies/{data_class}``."""

    retention_days: int = Field(
        ge=retention.MIN_RETENTION_DAYS,
        le=retention.MAX_RETENTION_DAYS,
        description=(
            "How long this tenant's rows in the store may live, in days."
        ),
    )
    status: Literal["active", "paused"] = Field(
        description=(
            "'active' is the consent that lets a month go; 'paused' is an explicit "
            "withdrawal."
        )
    )


def _gate_json(gate: retention.DropGate) -> dict:
    """The whole ``DropGate``, under its own names."""
    return {
        "tenant_count": gate.tenant_count,
        "missing_policies": gate.missing_policies,
        "max_days": gate.max_days,
        "may_drop": gate.may_drop,
        "reason": gate.reason,
    }


def _unblock_requires(gate: retention.DropGate) -> list[str]:
    """What would have to change for the gate to open, in the caller's terms."""
    if gate.may_drop:
        return []
    stores = ", ".join(sorted(retention.PARTITIONED_DATA_CLASSES))
    if gate.reason == retention.BLOCKED_NO_ACTIVE_TENANTS:
        return [
            "No active tenant exists, so there is nothing to consent and nothing "
            "to drop; this is not something a policy row can change."
        ]
    if gate.reason == retention.BLOCKED_NO_CHOSEN_POLICY:
        return [
            f"{gate.missing_policies} of {gate.tenant_count} active tenants have "
            f"no ACTIVE policy for {stores}; a shared month drops only once every "
            "one of them has chosen.",
            "Each of those tenants must PUT /analytics/retention/policies/"
            f"<data_class> with status 'active' (this deployment governs: {stores}).",
            "A 'paused' policy is a withdrawal, not an answer: it pins the month "
            "for every tenant, not only for the one that paused.",
        ]
    return [
        f"The longest horizon on record is {gate.max_days} days; every active "
        f"policy for {stores} must be greater than 0, since a zero would mean "
        "'delete everything now'."
    ]


def _gate_block(gate: retention.DropGate) -> dict:
    return {
        "gate": _gate_json(gate),
        "blocked_reason": None if gate.may_drop else gate.reason,
        "unblock_requires": _unblock_requires(gate),
    }


@router.get("/retention", response_model=schemas.RetentionPositionOut)
async def retention_position(ctx: AnalyticsReadCtx) -> dict[str, Any]:
    """§55-57 read: this tenant's retention policy, the shared gate, and what
    would unblock it."""
    gate = await retention.read_drop_gate(ctx.session)
    position = await retention.policy_position(ctx.session, ctx.tenant_id)
    return {"policies": position, **_gate_block(gate)}


@router.put("/retention/policies/{data_class}", response_model=schemas.RetentionPolicyWriteOut)
async def choose_retention_policy(
    data_class: str, body: RetentionPolicyChoice, ctx: AnalyticsWriteCtx
) -> dict[str, Any]:
    """§55-57 write: choose (or withdraw) this tenant's retention policy."""
    allowed = sorted(retention.CHOOSABLE_DATA_CLASSES)
    if data_class not in retention.CHOOSABLE_DATA_CLASSES:
        raise ValidationError(
            f"unknown data_class {data_class!r}: the stores a chosen policy can "
            f"execute against are {', '.join(allowed)}.",
            details={"data_class": data_class, "allowed": allowed},
        )

    previous = await retention.read_policy(ctx.session, ctx.tenant_id, data_class)
    enabled = body.status == retention.POLICY_ACTIVE
    try:
        chosen = await retention.choose_policy(
            ctx.session,
            ctx.tenant_id,
            data_class,
            retention_days=body.retention_days,
            enabled=enabled,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    gate = await retention.read_drop_gate(ctx.session)
    before = (
        None
        if previous is None
        else {
            "status": previous["status"],
            "retention_days": previous["retention_days"],
        }
    )
    await _write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        retention.CHOOSE_AUDIT_ACTION,
        retention.CHOOSE_AUDIT_RESOURCE,
        data_class,
        before=before,
        after={
            "data_class": data_class,
            "retention_days": body.retention_days,
            "status": body.status,
            "chosen": enabled,
            "shared_gate": _gate_json(gate),
        },
    )
    return {"policy": chosen, **_gate_block(gate)}
