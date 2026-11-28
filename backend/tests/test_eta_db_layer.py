"""ETA e-receipts on a real database: constraints, tenant isolation, callback lookup, and the
full issue path (device lock + previousUUID chain) through ``EInvoiceService``.

These need Postgres with the project's RLS applied (the ``db`` fixture); without one they are
skipped by the suite, exactly like the other RLS tests.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

import app.core.model_registry  # noqa: F401  (completes Base.metadata so every FK resolves)
from app.core.db import bind_tenant
from app.applications.apparel.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument, EInvoiceNotification
from app.applications.apparel.modules.einvoice.ports import EInvoiceContext, InvoiceLineItem, PartyInfo
from app.applications.apparel.modules.einvoice.providers.eta.provider import EtaEInvoiceProvider
from app.applications.apparel.modules.einvoice.service import EInvoiceService

pytestmark = pytest.mark.usefixtures("db")

PROFILE = {
    "environment": "preprod",
    "branch_code": "1",
    "activity_code": "4771",
    "branch_address": {
        "governate": "cairo",
        "region_city": "city center",
        "street": "16 street",
        "building_number": "14",
    },
}


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def _device(db, tenant_id, *, serial="POS-DB-1", key: str | None = None) -> EInvoiceDevice:
    d = EInvoiceDevice(
        tenant_id=tenant_id,
        device_name="Cairo POS",
        device_serial=serial,
        country_code="EG",
        provider_type="eta",
        metadata_info={"eta": PROFILE},
        notification_key_hash=_key_hash(key) if key else None,
    )
    db.add(d)
    await db.flush()
    return d


def _ctx(tenant_id, number: str, **over) -> EInvoiceContext:
    base = dict(
        tenant_id=tenant_id,
        country_code="EG",
        document_type="sale_receipt",
        invoice_number=number,
        issued_at=datetime.now(UTC),
        seller=PartyInfo(name="متجر", tax_id="674859545", country_code="EG"),
        currency="EGP",
        lines=[
            InvoiceLineItem(
                item_name="قميص",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("0.14"),
                sku="S1",
                item_code_type="EGS",
                item_code="EG-674859545-1",
                vat_subtype="V009",
            )
        ],
        subtotal=Decimal("100"),
        tax_total=Decimal("14"),
        grand_total=Decimal("114"),
        extras={"payment_tender": "cash"},
    )
    base.update(over)
    return EInvoiceContext(**base)


async def _other_tenant(db) -> uuid.UUID:
    t = uuid.uuid4()
    await db.execute(
        sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'Other')"),
        {"i": str(t), "s": f"o-{uuid.uuid4().hex[:8]}"},
    )
    return t


class TestSchema:
    async def test_new_tables_have_forced_tenant_rls(self, db):
        row = (
            await db.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'einvoice_notifications'"
                )
            )
        ).one()
        assert (row.relrowsecurity, row.relforcerowsecurity) == (True, True)

    async def test_cancelled_is_a_legal_status_and_junk_is_not(self, db, tenant_ctx):
        dev = await _device(db, tenant_ctx.tenant_id)
        ok = EInvoiceDocument(
            tenant_id=tenant_ctx.tenant_id,
            device_id=dev.id,
            country_code="EG",
            provider_type="eta",
            invoice_number="R-OK",
            document_type="sale_receipt",
            status="cancelled",
            invoice_hash="h",
            pih="",
        )
        db.add(ok)
        await db.flush()
        bad = EInvoiceDocument(
            tenant_id=tenant_ctx.tenant_id,
            device_id=dev.id,
            country_code="EG",
            provider_type="eta",
            invoice_number="R-BAD",
            document_type="sale_receipt",
            status="pending",  # NOT a stored status: the provider reports it as 'signed'
            invoice_hash="h",
            pih="",
        )
        db.add(bad)
        with pytest.raises(IntegrityError):
            await db.flush()


class TestEveryStatusTheLayerCanWriteIsLegal:
    """The sender and the callbacks write these words; the table's CHECK must accept them all.

    This is the test that would have caught the first version storing 'pending' (rejected by
    the database) while every mock-only test passed."""

    async def test_each_mapped_status_inserts(self, db, tenant_ctx):
        from app.applications.apparel.modules.einvoice.providers.eta.notifications import STORED_STATUS

        dev = await _device(db, tenant_ctx.tenant_id)
        for i, stored in enumerate(sorted(set(STORED_STATUS.values()))):
            db.add(
                EInvoiceDocument(
                    tenant_id=tenant_ctx.tenant_id,
                    device_id=dev.id,
                    country_code="EG",
                    provider_type="eta",
                    invoice_number=f"S-{i}",
                    document_type="sale_receipt",
                    status=stored,
                    invoice_hash="h",
                    pih="",
                )
            )
        await db.flush()

    def test_an_unknown_word_is_an_error_not_a_guess(self):
        from app.applications.apparel.modules.einvoice.providers.eta.notifications import stored_status

        with pytest.raises(ValueError):
            stored_status("approved")


class TestNotificationLedger:
    async def test_a_repeated_delivery_cannot_be_recorded_twice(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        db.add(EInvoiceNotification(tenant_id=tid, kind="receipt", delivery_id="D1", payload={}))
        await db.flush()
        db.add(EInvoiceNotification(tenant_id=tid, kind="receipt", delivery_id="D1", payload={}))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_same_delivery_id_in_another_kind_is_a_different_delivery(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        db.add(EInvoiceNotification(tenant_id=tid, kind="receipt", delivery_id="D1", payload={}))
        db.add(EInvoiceNotification(tenant_id=tid, kind="general", delivery_id="D1", payload={}))
        await db.flush()

    async def test_other_tenants_cannot_see_the_ledger_or_documents(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _device(db, tid)
        db.add(EInvoiceNotification(tenant_id=tid, kind="receipt", delivery_id="D9", payload={}))
        await db.flush()
        other = await _other_tenant(db)
        await bind_tenant(db, other)
        for table in ("einvoice_notifications", "einvoice_devices"):
            n = (await db.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert n == 0, f"{table} leaked rows to another tenant"
        assert dev.id  # sanity: the row existed for its own tenant


class TestCallbackKeyLookup:
    async def test_the_key_finds_exactly_its_device(self, db, tenant_ctx):
        dev = await _device(db, tenant_ctx.tenant_id, key="s3cret-key")
        # an unbound session, like a webhook arriving before any store is known
        await db.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
        row = (
            await db.execute(
                sa.text("SELECT * FROM resolve_eta_notification_device(:h)"),
                {"h": _key_hash("s3cret-key")},
            )
        ).one()
        assert (row.tenant_id, row.device_id, row.device_serial) == (
            tenant_ctx.tenant_id,
            dev.id,
            "POS-DB-1",
        )

    @pytest.mark.parametrize("h", [None, "", "abc", "0" * 64])
    async def test_unknown_or_malformed_keys_resolve_nothing(self, db, tenant_ctx, h):
        await _device(db, tenant_ctx.tenant_id, key="s3cret-key")
        await db.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
        rows = (
            await db.execute(sa.text("SELECT * FROM resolve_eta_notification_device(:h)"), {"h": h})
        ).all()
        assert rows == []

    async def test_the_lookup_returns_ids_never_credentials(self, db):
        cols = (
            await db.execute(
                sa.text(
                    "SELECT pg_get_function_result(oid) FROM pg_proc "
                    "WHERE proname = 'resolve_eta_notification_device'"
                )
            )
        ).scalar_one()
        assert "credentials" not in cols and "key" not in cols

    async def test_a_revoked_device_no_longer_resolves(self, db, tenant_ctx):
        dev = await _device(db, tenant_ctx.tenant_id, key="k2")
        dev.status = "revoked"
        await db.flush()
        await db.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
        rows = (
            await db.execute(
                sa.text("SELECT * FROM resolve_eta_notification_device(:h)"), {"h": _key_hash("k2")}
            )
        ).all()
        assert rows == []

    async def test_one_key_cannot_belong_to_two_devices(self, db, tenant_ctx):
        await _device(db, tenant_ctx.tenant_id, serial="A", key="same")
        db.add(
            EInvoiceDevice(
                tenant_id=tenant_ctx.tenant_id,
                device_name="B",
                device_serial="B",
                country_code="EG",
                provider_type="eta",
                notification_key_hash=_key_hash("same"),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()


class TestIssueThroughTheService:
    """The whole path on a real DB: row lock, counter, previousUUID chain, stored payload."""

    async def test_two_receipts_chain_by_uuid_and_store_what_was_built(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev0 = await _device(db, tid)
        first = await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, "R-1"), device_id=dev0.id)
        second = await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, "R-2"), device_id=dev0.id)

        assert first.status == "signed"  # stored, not delivered (no ETA credentials on the device)
        assert first.pih == ""  # first receipt of the POS
        assert second.pih == first.invoice_hash  # chained by the previous receipt's uuid
        assert first.invoice_hash != second.invoice_hash
        assert (first.icv, second.icv) == (1, 2)

        dev = (await db.execute(sa.select(EInvoiceDevice))).scalar_one()
        assert dev.icv_counter == 2 and dev.last_pih == second.invoice_hash
        assert "/receipts/search/" in first.qr_code and "IssuerRIN:674859545" in first.qr_code

    async def test_a_receipt_the_authority_would_reject_is_not_stored_and_does_not_move_the_chain(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        dev0 = await _device(db, tid)
        ok = await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, "R-1"), device_id=dev0.id)
        bad_line = InvoiceLineItem(
            item_name="x", quantity=Decimal("1"), unit_price=Decimal("5"), tax_rate=Decimal("0.14")
        )  # no registered item code
        from app.applications.apparel.modules.einvoice.providers.eta.provider import EtaValidationError

        with pytest.raises(EtaValidationError):
            await EInvoiceService.issue_einvoice(
                db, tid, _ctx(tid, "R-2", lines=[bad_line]), device_id=dev0.id
            )
        dev = (await db.execute(sa.select(EInvoiceDevice))).scalar_one()
        assert dev.icv_counter == 1 and dev.last_pih == ok.invoice_hash
        count = (await db.execute(sa.text("SELECT count(*) FROM einvoice_documents"))).scalar_one()
        assert count == 1

    async def test_an_unconfigured_egyptian_till_refuses_instead_of_reporting_cleared(
        self, db, tenant_ctx
    ):
        """The old default sent Egypt to the sandbox, which answered 'cleared' for a receipt no
        authority had seen. A new Egyptian till must be an ETA till, and with no profile it must
        refuse loudly."""
        from app.applications.apparel.modules.einvoice.providers.eta.provider import EtaValidationError

        tid = tenant_ctx.tenant_id
        with pytest.raises(EtaValidationError):
            await EInvoiceService.issue_einvoice(db, tid, _ctx(tid, "R-NEW"))
        dev = (await db.execute(sa.select(EInvoiceDevice))).scalar_one()
        assert dev.provider_type == "eta"
        n = (await db.execute(sa.text("SELECT count(*) FROM einvoice_documents"))).scalar_one()
        assert n == 0

    async def test_provider_registered_for_eta_is_the_new_one(self):
        from app.applications.apparel.modules.einvoice.registry import get_einvoice_provider

        assert isinstance(get_einvoice_provider("eta", country_code="EG"), EtaEInvoiceProvider)
        assert isinstance(get_einvoice_provider(country_code="EG"), EtaEInvoiceProvider)
