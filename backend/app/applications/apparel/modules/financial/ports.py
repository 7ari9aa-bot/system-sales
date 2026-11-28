"""Payment port abstraction and Sandbox adapter (V12 Wave C / ADR-060)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class PaymentChargeResult:
    status: str  # "SUCCEEDED" | "FAILED" | "AMBIGUOUS"
    provider_reference: str
    amount: Decimal
    currency: str
    fee_amount: Decimal = Decimal("0.0000")
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class PaymentRefundResult:
    status: str  # "SUCCEEDED" | "FAILED" | "AMBIGUOUS"
    provider_reference: str
    amount: Decimal
    currency: str
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass(frozen=True)
class PaymentStatusResult:
    status: str  # "SUCCEEDED" | "FAILED" | "PENDING"
    provider_reference: str
    amount: Decimal
    currency: str
    raw_response: dict[str, Any] | None = None


class PaymentPort(Protocol):
    """Abstract interface defining required provider capabilities."""

    async def charge(
        self,
        tenant_id: uuid.UUID,
        *,
        amount: Decimal,
        currency: str,
        source_token: str,
        reference_id: uuid.UUID | str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentChargeResult: ...

    async def refund(
        self,
        tenant_id: uuid.UUID,
        *,
        provider_reference: str,
        amount: Decimal,
        currency: str,
        reason: str | None = None,
    ) -> PaymentRefundResult: ...

    async def verify(
        self,
        tenant_id: uuid.UUID,
        *,
        provider_reference: str,
    ) -> PaymentStatusResult: ...


class SandboxPaymentAdapter(PaymentPort):
    """Deterministic, zero-network sandbox adapter for CI, local tests, and simulation.

    Tokens:
    - 'tok_success' (default): immediately succeeds with zero fee
    - 'tok_decline': immediately declines with 'insufficient_funds'
    - 'tok_timeout' / 'tok_ambiguous': returns AMBIGUOUS to test reconciliation
    """

    def __init__(self, fee_percentage: Decimal = Decimal("0.025")) -> None:
        self.fee_percentage = fee_percentage
        self.charges: dict[str, PaymentChargeResult] = {}
        self.refunds: dict[str, PaymentRefundResult] = {}

    async def charge(
        self,
        tenant_id: uuid.UUID,
        *,
        amount: Decimal,
        currency: str,
        source_token: str,
        reference_id: uuid.UUID | str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentChargeResult:
        tx_ref = f"sbx_ch_{uuid.uuid4().hex[:16]}"
        token = source_token.strip().lower()

        if "decline" in token:
            result = PaymentChargeResult(
                status="FAILED",
                provider_reference=tx_ref,
                amount=amount,
                currency=currency,
                error_code="card_declined",
                error_message="Card was declined by issuing bank",
                raw_response={"sandbox": True, "token": source_token},
            )
        elif "timeout" in token or "ambiguous" in token:
            result = PaymentChargeResult(
                status="AMBIGUOUS",
                provider_reference=tx_ref,
                amount=amount,
                currency=currency,
                error_code="gateway_timeout",
                error_message="Provider timeout awaiting upstream authorization",
                raw_response={"sandbox": True, "token": source_token},
            )
        else:
            fee = (amount * self.fee_percentage).quantize(Decimal("0.0001"))
            result = PaymentChargeResult(
                status="SUCCEEDED",
                provider_reference=tx_ref,
                amount=amount,
                currency=currency,
                fee_amount=fee,
                raw_response={"sandbox": True, "token": source_token},
            )

        self.charges[tx_ref] = result
        return result

    async def refund(
        self,
        tenant_id: uuid.UUID,
        *,
        provider_reference: str,
        amount: Decimal,
        currency: str,
        reason: str | None = None,
    ) -> PaymentRefundResult:
        rf_ref = f"sbx_rf_{uuid.uuid4().hex[:16]}"

        if provider_reference not in self.charges:
            return PaymentRefundResult(
                status="FAILED",
                provider_reference=rf_ref,
                amount=amount,
                currency=currency,
                error_code="original_charge_not_found",
                error_message=f"No sandbox charge exists for {provider_reference}",
            )

        original = self.charges[provider_reference]
        if original.status != "SUCCEEDED":
            return PaymentRefundResult(
                status="FAILED",
                provider_reference=rf_ref,
                amount=amount,
                currency=currency,
                error_code="cannot_refund_unsuccessful_charge",
                error_message=f"Original charge status is {original.status}",
            )

        result = PaymentRefundResult(
            status="SUCCEEDED",
            provider_reference=rf_ref,
            amount=amount,
            currency=currency,
            raw_response={"sandbox": True, "original": provider_reference},
        )
        self.refunds[rf_ref] = result
        return result

    async def verify(
        self,
        tenant_id: uuid.UUID,
        *,
        provider_reference: str,
    ) -> PaymentStatusResult:
        if provider_reference in self.charges:
            c = self.charges[provider_reference]
            # Sandbox resolution: ambiguous charges resolve to SUCCEEDED upon verification query
            resolved_status = "SUCCEEDED" if c.status == "AMBIGUOUS" else c.status
            return PaymentStatusResult(
                status=resolved_status,
                provider_reference=provider_reference,
                amount=c.amount,
                currency=c.currency,
                raw_response=c.raw_response,
            )

        return PaymentStatusResult(
            status="FAILED",
            provider_reference=provider_reference,
            amount=Decimal("0.0000"),
            currency="SAR",
            raw_response={"error": "not_found"},
        )
