"""E-invoicing orchestrator service — atomic hash chaining, monotonic ICV, and submission."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.applications.apparel.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument
from app.applications.apparel.modules.einvoice.ports import (
    EInvoiceContext,
    EInvoiceProvider,
)
from app.applications.apparel.modules.einvoice.registry import get_einvoice_provider


class EInvoiceService:
    """Orchestrator for compliant electronic invoice issuance, signing, and transmission."""

    @staticmethod
    async def get_or_create_device(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        country_code: str,
        *,
        provider_type: str | None = None,
        device_serial: str = "DEFAULT-POS-01",
        device_name: str = "Primary Cashier Register",
    ) -> EInvoiceDevice:
        """Fetch or initialize a tenant's fiscal register device."""
        clean_country = country_code.strip().upper()
        stmt = (
            select(EInvoiceDevice)
            .where(
                EInvoiceDevice.tenant_id == tenant_id,
                EInvoiceDevice.device_serial == device_serial,
            )
            .with_for_update()
        )
        device = (await session.execute(stmt)).scalar_one_or_none()
        if device is not None:
            return device

        # Each country's own authority provider. Falling back to the sandbox for Egypt made a
        # till report receipts as "cleared" that no authority had ever seen.
        default_provider = {"SA": "zatca", "EG": "eta", "AE": "peppol_ae"}.get(
            clean_country, "sandbox"
        )
        chosen_provider = provider_type or default_provider

        device = EInvoiceDevice(
            tenant_id=tenant_id,
            device_name=device_name,
            device_serial=device_serial,
            country_code=clean_country,
            provider_type=chosen_provider,
            status="active",
            icv_counter=0,
            last_pih=None,
        )
        session.add(device)
        await session.flush()
        return device

    @staticmethod
    async def issue_einvoice(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        context: EInvoiceContext,
        *,
        device_id: uuid.UUID | None = None,
        provider: EInvoiceProvider | None = None,
        order_id: uuid.UUID | None = None,
        receipt_id: uuid.UUID | None = None,
    ) -> EInvoiceDocument:
        """Issue, cryptographically sign, and submit an electronic invoice with atomic chaining.

        Guarantees:
        1. Monotonic ICV: Lock device row to serialize counter increments without gaps.
        2. Tamper-evident Hash Chain: Binds current document digest with `last_pih`.
        3. Fiscal Audit Evidence: Full raw XML/JSON, QR, and authority responses stored immutably.
        """
        # 1. Fetch locked device
        if device_id:
            device = (
                await session.execute(
                    select(EInvoiceDevice)
                    .where(
                        EInvoiceDevice.tenant_id == tenant_id,
                        EInvoiceDevice.id == device_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not device:
                raise NotFoundError(f"E-invoice device '{device_id}' not found")
        else:
            device = await EInvoiceService.get_or_create_device(
                session, tenant_id, context.country_code
            )

        # 2. Check duplicate invoice number
        existing = (
            await session.execute(
                select(EInvoiceDocument).where(
                    EInvoiceDocument.tenant_id == tenant_id,
                    EInvoiceDocument.invoice_number == context.invoice_number,
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(
                f"E-invoice document '{context.invoice_number}' has already been issued"
            )

        # 3. Resolve active provider
        active_provider = provider or get_einvoice_provider(
            device.provider_type, country_code=context.country_code
        )

        # 4. Generate canonical payload (XML/JSON). Providers that chain by the previous
        #    document (ETA) need the locked device row; it is handed over through ``extras``
        #    on a copy so the caller's frozen context is never mutated.
        build_context = replace(context, extras={**context.extras, "_device": device})
        payload = await active_provider.generate_document(build_context)

        # 5. Cryptographically sign and stamp
        signed = await active_provider.sign_document(build_context, payload, device)

        # 6. Update device state (advance ICV and forward PIH chain)
        device.icv_counter = signed.icv
        device.last_pih = signed.invoice_hash
        await session.flush()

        # 7. Transmit to authority (clearance or reporting)
        submission = await active_provider.submit(signed, device)

        # 8. Record immutable document
        doc = EInvoiceDocument(
            tenant_id=tenant_id,
            device_id=device.id,
            country_code=context.country_code,
            provider_type=active_provider.provider_type,
            order_id=order_id,
            receipt_id=receipt_id,
            invoice_number=context.invoice_number,
            document_type=context.document_type,
            status=submission.status,
            icv=signed.icv,
            invoice_hash=signed.invoice_hash,
            pih=signed.pih,
            qr_code=signed.qr_code,
            cryptographic_stamp=signed.signature,
            raw_payload=signed.raw_content,
            authority_uuid=submission.authority_uuid,
            authority_response=submission.raw_response,
            errors=submission.errors,
            issued_at=context.issued_at,
            cleared_at=datetime.now(UTC) if submission.status == "cleared" else None,
            reported_at=datetime.now(UTC) if submission.status == "reported" else None,
        )
        session.add(doc)
        await session.flush()
        return doc

    @staticmethod
    async def get_document_by_receipt(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        receipt_id: uuid.UUID,
    ) -> EInvoiceDocument | None:
        """Find the electronic invoice associated with a POS receipt."""
        stmt = select(EInvoiceDocument).where(
            EInvoiceDocument.tenant_id == tenant_id,
            EInvoiceDocument.receipt_id == receipt_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
