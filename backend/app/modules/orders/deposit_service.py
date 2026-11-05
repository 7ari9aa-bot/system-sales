"""Versioned merchant deposit rules and read-only order previews."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_row
from app.core.events.writer import add_outbox_event
from app.core.tenancy import resolve_tenant_currency
from app.modules.errors import ValidationError
from app.modules.orders.deposit import (
    BASE_GRAND_TOTAL,
    MAX_POLICY_AMOUNT,
    TYPE_FIXED,
    TYPE_NONE,
    TYPE_PERCENTAGE,
    DepositRule,
    currency_amount,
    deposit_for,
    deposit_refusal,
    remaining_balance,
)
from app.modules.orders.models import DepositPolicy, OrderPayment, Refund
from app.modules.orders.money import COLLECTED_PAYMENT_STATUSES, net_collected
from app.modules.orders.service import OrderService

__all__ = ["DepositService"]


def _policy_value(value: object, field: str, currency: str, *, percentage: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError(f"{field} must be a finite number")
        if amount < 0:
            raise ValueError(f"{field} must not be negative")
        if amount > MAX_POLICY_AMOUNT:
            raise ValueError(f"{field} exceeds the policy amount limit {MAX_POLICY_AMOUNT}")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError(f"{field} must have at most 2 decimal places")
        # Percentage points are dimensionless, including for zero-decimal currencies.
        return (
            amount.quantize(Decimal("0.01"))
            if percentage
            else currency_amount(amount, field, currency)
        )
    except (ValueError, ArithmeticError) as exc:
        raise ValidationError(str(exc)) from exc


class DepositService:
    @staticmethod
    async def get_active(session: AsyncSession, tenant_id: uuid.UUID) -> DepositPolicy | None:
        return (
            await session.execute(
                select(DepositPolicy).where(
                    DepositPolicy.tenant_id == tenant_id, DepositPolicy.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_policies(session: AsyncSession, tenant_id: uuid.UUID) -> list[DepositPolicy]:
        rows = (
            await session.execute(
                select(DepositPolicy)
                .where(DepositPolicy.tenant_id == tenant_id)
                .order_by(DepositPolicy.version.desc())
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def save_policy(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        name: str,
        deposit_type: str,
        deposit_value: object,
        calculation_base: str = BASE_GRAND_TOTAL,
        minimum_deposit: object = None,
        maximum_deposit: object = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> DepositPolicy:
        name = name.strip()
        if not name or len(name) > 127:
            raise ValidationError("name must contain between 1 and 127 characters")
        currency = await resolve_tenant_currency(session, tenant_id)
        rule = DepositRule(
            deposit_type=deposit_type,
            deposit_value=_policy_value(
                deposit_value, "deposit_value", currency, percentage=deposit_type == TYPE_PERCENTAGE
            ),
            calculation_base=calculation_base,
            minimum_deposit=(
                None
                if minimum_deposit is None
                else _policy_value(minimum_deposit, "minimum_deposit", currency)
            ),
            maximum_deposit=(
                None
                if maximum_deposit is None
                else _policy_value(maximum_deposit, "maximum_deposit", currency)
            ),
        )
        refusal = deposit_refusal(rule, currency=currency)
        if refusal:
            raise ValidationError(refusal)
        if rule.deposit_type == TYPE_NONE:
            rule = DepositRule(deposit_type=TYPE_NONE)

        # Serialize max(version)+1 and deactivation across independent transactions.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"deposit_policy:{tenant_id}"},
        )
        active = await DepositService.get_active(session, tenant_id)
        if (
            active
            and active.name == name
            and active.currency == currency
            and DepositRule.from_policy(active) == rule
        ):
            return active
        highest = (
            await session.execute(
                select(func.max(DepositPolicy.version)).where(DepositPolicy.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if active:
            active.is_active = False
            # Flush UPDATE before INSERT to satisfy the one-active-row index.
            await session.flush()
        policy = DepositPolicy(
            tenant_id=tenant_id,
            name=name,
            version=1 if highest is None else int(highest) + 1,
            is_active=True,
            deposit_type=rule.deposit_type,
            deposit_value=rule.deposit_value,
            currency=currency,
            calculation_base=rule.calculation_base,
            minimum_deposit=rule.minimum_deposit,
            maximum_deposit=rule.maximum_deposit,
        )
        session.add(policy)
        await session.flush()
        snapshot = {
            "name": name,
            "version": policy.version,
            "deposit_type": rule.deposit_type,
            "deposit_value": str(rule.deposit_value),
            "currency": currency,
            "calculation_base": rule.calculation_base,
            "minimum_deposit": None if rule.minimum_deposit is None else str(rule.minimum_deposit),
            "maximum_deposit": None if rule.maximum_deposit is None else str(rule.maximum_deposit),
        }
        await write_audit_row(
            session,
            tenant_id,
            actor_user_id,
            "order.deposit_policy_changed",
            "deposit_policy",
            str(policy.id),
            before=None if active is None else {"id": str(active.id), "version": active.version},
            after=snapshot,
        )
        await add_outbox_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="order",
            aggregate_id=policy.id,
            event_type="order.deposit_policy_changed",
            payload={"policy_id": str(policy.id), "version": policy.version},
        )
        return policy

    @staticmethod
    async def preview_deposit(
        session: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> dict[str, Any]:
        """Current-policy calculation, not a frozen quote or payment instruction."""
        order = await OrderService.get(session, tenant_id, order_id, with_items=False)
        policy = await DepositService.get_active(session, tenant_id)
        deposit = currency_amount(0, "deposit", order.currency)
        if policy:
            has_absolute_money = (
                policy.deposit_type == TYPE_FIXED
                or policy.minimum_deposit is not None
                or policy.maximum_deposit is not None
            )
            if order.currency != policy.currency and has_absolute_money:
                raise ValidationError(
                    f"the active deposit policy is written in {policy.currency}, but the order "
                    f"is in {order.currency}; fixed amounts and bands cannot change currency"
                )
            deposit = deposit_for(
                DepositRule.from_policy(policy),
                currency=order.currency,
                subtotal=order.subtotal,
                discount_total=order.discount_total,
                shipping_total=order.shipping_total,
                tax_total=order.tax_total,
                grand_total=order.grand_total,
            )
        collected = (
            select(func.coalesce(func.sum(OrderPayment.amount), 0))
            .where(
                OrderPayment.tenant_id == tenant_id,
                OrderPayment.order_id == order.id,
                OrderPayment.status.in_(COLLECTED_PAYMENT_STATUSES),
            )
            .scalar_subquery()
        )
        refunded = (
            select(func.coalesce(func.sum(Refund.amount), 0))
            .join(OrderPayment, OrderPayment.id == Refund.payment_id)
            .where(
                Refund.tenant_id == tenant_id,
                OrderPayment.tenant_id == tenant_id,
                OrderPayment.order_id == order.id,
                Refund.status != "rejected",
            )
            .scalar_subquery()
        )
        gross, returned = (await session.execute(select(collected, refunded))).one()
        return {
            "order_id": order.id,
            "currency": order.currency,
            "grand_total": currency_amount(order.grand_total, "grand_total", order.currency),
            "deposit": deposit,
            "remaining_balance": remaining_balance(
                order.grand_total, net_collected(gross, returned), currency=order.currency
            ),
            "policy_version": policy.version if policy else None,
            "deposit_type": policy.deposit_type if policy else None,
        }
