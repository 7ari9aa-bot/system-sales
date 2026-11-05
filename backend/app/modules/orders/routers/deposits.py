"""Merchant deposit rules and current-policy order previews."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.deposit import BASE_GRAND_TOTAL
from app.modules.orders.deposit_service import DepositService
from app.modules.orders.models import DepositPolicy

from ._deps import DepositSettingsCtx, DepositSettingsReadCtx, OrdersReadCtx, router


class DepositPolicyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=127)
    deposit_type: str = Field(min_length=1, max_length=31)
    deposit_value: Decimal = Field(ge=0)
    calculation_base: str = Field(default=BASE_GRAND_TOTAL, min_length=1, max_length=31)
    minimum_deposit: Decimal | None = Field(default=None, ge=0)
    maximum_deposit: Decimal | None = Field(default=None, ge=0)


def _policy_out(policy: DepositPolicy) -> dict:
    return {
        "id": str(policy.id),
        "name": policy.name,
        "version": policy.version,
        "is_active": policy.is_active,
        "deposit_type": policy.deposit_type,
        "deposit_value": str(policy.deposit_value),
        "currency": policy.currency,
        "calculation_base": policy.calculation_base,
        "minimum_deposit": None if policy.minimum_deposit is None else str(policy.minimum_deposit),
        "maximum_deposit": None if policy.maximum_deposit is None else str(policy.maximum_deposit),
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


@router.get("/orders/deposit-policies")
async def list_deposit_policies(ctx: DepositSettingsReadCtx):
    """Every deposit version this tenant has saved, newest first."""
    rows = await DepositService.list_policies(ctx.session, ctx.tenant_id)
    return [_policy_out(p) for p in rows]


@router.post("/orders/deposit-policies", status_code=201)
async def create_deposit_policy(body: DepositPolicyCreateRequest, ctx: DepositSettingsCtx):
    """Save an active policy version; unchanged retries reuse the existing version."""
    policy = await DepositService.save_policy(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        deposit_type=body.deposit_type,
        deposit_value=body.deposit_value,
        calculation_base=body.calculation_base,
        minimum_deposit=body.minimum_deposit,
        maximum_deposit=body.maximum_deposit,
        actor_user_id=ctx.user.id,
    )
    return _policy_out(policy)


@router.get("/orders/{order_id}/deposit")
async def get_order_deposit(ctx: OrdersReadCtx, order_id: uuid.UUID):
    """Preview stored order amounts under today's policy, not a frozen customer quote."""
    preview = await DepositService.preview_deposit(ctx.session, ctx.tenant_id, order_id)
    return {
        "order_id": str(preview["order_id"]),
        "currency": preview["currency"],
        "grand_total": str(preview["grand_total"]),
        "deposit": str(preview["deposit"]),
        "remaining_balance": str(preview["remaining_balance"]),
        "policy_version": preview["policy_version"],
        "deposit_type": preview["deposit_type"],
    }


__all__ = [
    "DepositPolicyCreateRequest",
    "_policy_out",
    "create_deposit_policy",
    "get_order_deposit",
    "list_deposit_policies",
]
