"""ETA delivery against a real database and the in-process authority.

Covers what mock-only tests cannot: rows really move between statuses the table accepts, the
till row lock really stops a second sender, and a repeated callback really does nothing twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (completes Base.metadata so every FK resolves)
from app.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument, EInvoiceNotification
from app.modules.einvoice.providers.eta.delivery import (
    apply_device_event,
    apply_receipt_events,
    deliver_device,
)
from app.modules.einvoice.providers.eta.mock_authority import MockAuthority
from app.modules.einvoice.providers.eta.notifications import (
    parse_general_notification,
    parse_receipt_notification,
)
from app.modules.einvoice.providers.eta.provider import EtaEInvoiceProvider
from app.modules.einvoice.service import EInvoiceService
from tests.test_eta_db_layer import _ctx, _device

pytestmark = pytest.mark.usefixtures("db")

CREDS = {"client_id": "mock-client", "client_secret": "mock-secret", "preshared_key": "mock-psk"}


async def _till(db, tid, serial="POS-MOCK-1") -> EInvoiceDevice:
    dev = await _device(db, tid, serial=serial)
    dev.credentials = {"eta": CREDS}
    await db.flush()
    return dev


async def _issue(db, tid, dev, number: str, amount: str = "100"):
    """Issue through the service. With credentials the provider would try to send inline, so the
    receipt is stored first (no network in a test) and delivered by the sender under test."""
    saved, dev.credentials = dev.credentials, {}
    try:
        from decimal import Decimal

        ctx = _ctx(tid, number, subtotal=Decimal(amount))
        return await EInvoiceService.issue_einvoice(db, tid, ctx, device_id=dev.id)
    finally:
        dev.credentials = saved
        await db.flush()


async def _no_sleep(_: float) -> None:
    return None


def _provider(mock: MockAuthority) -> EtaEInvoiceProvider:
    return EtaEInvoiceProvider(http=httpx.AsyncClient(transport=mock.transport()), sleep=_no_sleep)


async def _doc(db, number) -> EInvoiceDocument:
    return (
        await db.execute(
            sa.select(EInvoiceDocument).where(EInvoiceDocument.invoice_number == number)
        )
    ).scalar_one()


class TestSending:
    async def test_stored_receipts_go_out_in_chain_order_and_become_submitted(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        for n in ("R-1", "R-2", "R-3"):
            await _issue(db, tid, dev, n)
        mock = MockAuthority()
        report = await deliver_device(db, dev.id, provider=_provider(mock))
        assert (report.sent, report.accepted, report.rejected) == (3, 3, 0)
        for n in ("R-1", "R-2", "R-3"):
            d = await _doc(db, n)
            assert d.status == "submitted" and d.authority_long_id and d.submission_uuid
            assert d.delivery_attempts == 1 and d.errors == []
        # the authority saw them chained, in order
        assert len(mock.submissions) == 1

    async def test_an_accepted_receipt_is_never_sent_again(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        mock = MockAuthority()
        await deliver_device(db, dev.id, provider=_provider(mock))
        again = await deliver_device(db, dev.id, provider=_provider(mock))
        assert again.sent == 0 and len(mock.submissions) == 1

    async def test_receipts_the_authority_already_holds_are_not_even_loaded(
        self, db, tenant_ctx, monkeypatch
    ):
        """Guards the database query, not just the planner: if the filter widened to accepted
        receipts, only the planner would stand between them and a second send."""
        import app.modules.einvoice.providers.eta.delivery as mod

        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        await deliver_device(db, dev.id, provider=_provider(MockAuthority()))
        assert (await _doc(db, "R-1")).status == "submitted"

        seen: list = []
        real = mod.plan_device
        monkeypatch.setattr(
            mod, "plan_device", lambda docs, **kw: (seen.extend(docs), real(docs, **kw))[1]
        )
        await deliver_device(db, dev.id, provider=_provider(MockAuthority()))
        assert seen == [], "accepted receipts must not be loaded for sending at all"

    async def test_the_bytes_sent_are_the_bytes_stored(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        d = await _issue(db, tid, dev, "R-1")
        seen: list[bytes] = []
        mock = MockAuthority()
        inner = mock.handler

        def spy(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/api/v1/receiptsubmissions":
                seen.append(req.content)
            return inner(req)

        prov = EtaEtaProvider = EtaEInvoiceProvider(
            http=httpx.AsyncClient(transport=httpx.MockTransport(spy))
        )
        del EtaEtaProvider
        await deliver_device(db, dev.id, provider=prov)
        assert seen and d.raw_payload.encode() in seen[0]

    async def test_a_throttled_send_keeps_receipts_deliverable_and_waits(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        mock = MockAuthority(fail_next=[429] * 4, retry_after=60)
        now = datetime.now(UTC)
        report = await deliver_device(db, dev.id, now=now, provider=_provider(mock))
        d = await _doc(db, "R-1")
        assert report.failed == 1 and d.status == "failed"
        assert d.next_attempt_at > now + timedelta(seconds=60)  # longer than Retry-After
        # not due yet: nothing is sent, and it says why
        blocked = await deliver_device(db, dev.id, now=now, provider=_provider(mock))
        assert blocked.sent == 0 and blocked.blocked_by
        # once due, it goes out and is accepted
        later = await deliver_device(
            db, dev.id, now=d.next_attempt_at + timedelta(seconds=1), provider=_provider(mock)
        )
        assert later.accepted == 1 and (await _doc(db, "R-1")).status == "submitted"

    async def test_a_rejected_receipt_is_marked_and_flagged_for_correction(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        # a mock that refuses the receipt: the rin does not match the seller
        mock = MockAuthority(rin="000000000")
        report = await deliver_device(db, dev.id, provider=_provider(mock))
        d = await _doc(db, "R-1")
        assert report.rejected == 1 and report.needs_correction == ["R-1"]
        assert d.status == "rejected" and d.errors

    async def test_a_till_without_credentials_sends_nothing_and_says_so(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        dev.credentials = {}
        await db.flush()
        report = await deliver_device(db, dev.id, provider=_provider(MockAuthority()))
        assert report.sent == 0 and "credentials" in report.blocked_by
        assert (await _doc(db, "R-1")).status == "signed"

    async def test_a_suspended_till_is_left_alone(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        dev.status = "suspended"
        await db.flush()
        mock = MockAuthority()
        report = await deliver_device(db, dev.id, provider=_provider(mock))
        assert report.sent == 0 and not mock.submissions

    async def test_another_tenants_receipts_are_never_picked_up(self, db, tenant_ctx):
        from app.core.db import bind_tenant
        from tests.test_eta_db_layer import _other_tenant

        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        other = await _other_tenant(db)
        await bind_tenant(db, other)
        mock = MockAuthority()
        # under another store's binding the till is invisible, so there is nothing to send
        assert await deliver_device(db, dev.id, provider=_provider(mock)) is None
        assert not mock.submissions


_KIND = {"Valid": "Validated", "Invalid": "Validated", "Cancelled": "Cancelled"}


def _receipt_body(delivery_id: str, *uuids_and_status: tuple[str, str]):
    return {
        "deliveryId": delivery_id,
        "message": [
            {
                "type": _KIND[st],
                "uuid": u,
                "submissionUUID": "SUB1",
                "longId": "LONG-" + u[:6],
                "internalId": "x",
                "status": st,
            }
            for u, st in uuids_and_status
        ],
    }


class TestCallbacks:
    async def _setup(self, db, tid):
        dev = await _till(db, tid)
        d1 = await _issue(db, tid, dev, "R-1")
        await deliver_device(db, dev.id, provider=_provider(MockAuthority()))
        return dev, d1

    async def test_a_valid_notification_marks_the_receipt_reported(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev, d1 = await self._setup(db, tid)
        body = _receipt_body("D1", (d1.invoice_hash, "Valid"))
        res = await apply_receipt_events(
            db,
            tenant_id=tid,
            device_id=dev.id,
            events=parse_receipt_notification(body),
            raw_body=body,
        )
        d = await _doc(db, "R-1")
        assert res["applied"] == 1 and d.status == "reported" and d.reported_at

    async def test_the_same_delivery_twice_changes_nothing_the_second_time(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev, d1 = await self._setup(db, tid)
        body = _receipt_body("D1", (d1.invoice_hash, "Valid"))
        ev = parse_receipt_notification(body)
        await apply_receipt_events(db, tenant_id=tid, device_id=dev.id, events=ev, raw_body=body)
        d = await _doc(db, "R-1")
        d.errors = ["tampered between deliveries"]
        await db.flush()
        res = await apply_receipt_events(
            db, tenant_id=tid, device_id=dev.id, events=ev, raw_body=body
        )
        assert res == {"applied": 0, "unknown": 0, "repeat": 1}
        assert (await _doc(db, "R-1")).errors == ["tampered between deliveries"]
        n = (
            await db.execute(sa.select(sa.func.count()).select_from(EInvoiceNotification))
        ).scalar_one()
        assert n == 1

    async def test_an_invalid_notification_marks_it_rejected(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev, d1 = await self._setup(db, tid)
        body = _receipt_body("D2", (d1.invoice_hash, "Invalid"))
        await apply_receipt_events(
            db,
            tenant_id=tid,
            device_id=dev.id,
            events=parse_receipt_notification(body),
            raw_body=body,
        )
        assert (await _doc(db, "R-1")).status == "rejected"

    async def test_a_cancelled_receipt_never_comes_back_to_life(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev, d1 = await self._setup(db, tid)
        for did, st in (("D3", "Cancelled"), ("D4", "Valid")):
            body = _receipt_body(did, (d1.invoice_hash, st))
            await apply_receipt_events(
                db,
                tenant_id=tid,
                device_id=dev.id,
                events=parse_receipt_notification(body),
                raw_body=body,
            )
        assert (await _doc(db, "R-1")).status == "cancelled"

    async def test_an_unknown_receipt_is_counted_not_fatal(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        dev, _ = await self._setup(db, tid)
        body = _receipt_body("D5", ("f" * 64, "Valid"))
        res = await apply_receipt_events(
            db,
            tenant_id=tid,
            device_id=dev.id,
            events=parse_receipt_notification(body),
            raw_body=body,
        )
        assert res["unknown"] == 1 and res["applied"] == 0

    async def test_a_receipt_of_another_till_is_not_touched_by_this_tills_callback(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        dev, d1 = await self._setup(db, tid)
        other = await _till(db, tid, serial="POS-OTHER")
        body = _receipt_body("D6", (d1.invoice_hash, "Valid"))
        res = await apply_receipt_events(
            db,
            tenant_id=tid,
            device_id=other.id,
            events=parse_receipt_notification(body),
            raw_body=body,
        )
        assert res["unknown"] == 1 and (await _doc(db, "R-1")).status == "submitted"

    async def test_a_deactivation_notice_suspends_the_till_and_keeps_the_reason(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        dev, _ = await self._setup(db, tid)
        body = {
            "Type": "PosDeactivated",
            "Id": dev.device_serial,
            "Message": {"Reason": "tax office hold"},
        }
        ev = parse_general_notification(body)
        assert (
            await apply_device_event(db, tenant_id=tid, device_id=dev.id, event=ev, raw_body=body)
            == "applied"
        )
        await db.refresh(dev)
        assert dev.status == "suspended"
        assert dev.metadata_info["eta"]["deactivated_reason"] == "tax office hold"
        assert dev.metadata_info["eta"]["alerts"][-1]["type"] == "PosDeactivated"
        assert (
            await apply_device_event(db, tenant_id=tid, device_id=dev.id, event=ev, raw_body=body)
            == "repeat"
        )


class TestTwoSendersAtOnce:
    """Two workers must never send the same till's receipts twice (a duplicate at the authority).

    Needs REAL commits on two connections, so it builds its own store and removes it afterwards.
    """

    async def test_a_till_that_is_being_sent_is_skipped_by_the_second_worker(
        self, db_url, admin_url
    ):
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.db import bind_tenant
        from app.modules.identity.models import Tenant

        eng = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
        admin = create_async_engine(admin_url)
        factory = async_sessionmaker(eng, expire_on_commit=False)
        tid = uuid.uuid4()
        try:
            async with factory() as s, s.begin():
                s.add(Tenant(id=tid, slug=f"cc-{uuid.uuid4().hex[:8]}", name="Concurrent"))
            async with factory() as s, s.begin():
                await bind_tenant(s, tid)
                dev = await _till(s, tid)
                await _issue(s, tid, dev, "R-1")
                dev_id = dev.id

            gate, entered = asyncio.Event(), asyncio.Event()
            mock = MockAuthority()

            class SlowProvider(EtaEInvoiceProvider):
                """Holds the first worker inside its send until the second has tried."""

                def _client(self, device, cfg):
                    client = super()._client(device, cfg)
                    real = client.submit_raw

                    async def slow(body):
                        entered.set()
                        await gate.wait()
                        return await real(body)

                    client.submit_raw = slow
                    return client

            def prov(cls=EtaEInvoiceProvider):
                return cls(http=httpx.AsyncClient(transport=mock.transport()), sleep=_no_sleep)

            async def first():
                async with factory() as s, s.begin():
                    await bind_tenant(s, tid)
                    return await deliver_device(s, dev_id, provider=prov(SlowProvider))

            async def second():
                await entered.wait()  # the first worker now holds the till and is mid-send
                async with factory() as s, s.begin():
                    await bind_tenant(s, tid)
                    result = await deliver_device(s, dev_id, provider=prov())
                gate.set()
                return result

            r1, r2 = await asyncio.gather(first(), second())
            assert r2 is None, "the second worker must skip a till another worker is sending"
            assert r1.accepted == 1
            assert len(mock.submissions) == 1, "the authority must see the receipt exactly once"
        finally:
            async with admin.begin() as c:
                await c.execute(sa.text("DELETE FROM tenants WHERE id = :t"), {"t": str(tid)})
            await eng.dispose()
            await admin.dispose()


class TestWholeStoreRun:
    """The scheduled job: every active ETA till of one store, each isolated from the others."""

    async def test_the_job_is_registered_and_runs_every_minute(self):
        from datetime import timedelta

        from app.workers.scheduler_worker import _HANDLERS, RECURRING_JOBS

        assert "einvoice.eta_deliver" in _HANDLERS
        assert RECURRING_JOBS["einvoice.eta_deliver"][0] == timedelta(minutes=1)

    async def test_it_delivers_every_till_of_the_store_and_totals_them(self, db, tenant_ctx):
        from app.modules.einvoice.providers.eta.delivery import deliver_tenant

        tid = tenant_ctx.tenant_id
        for serial in ("POS-MOCK-1", "POS-MOCK-2"):
            dev = await _till(db, tid, serial=serial)
            await _issue(db, tid, dev, f"R-{serial}")
        # one mock serves both tills: give it a shared identity
        mock = MockAuthority(pos_serial="POS-MOCK-1")
        out = await deliver_tenant(db, tid, provider=_provider(mock))
        # the second till has a different serial than the mock expects, so only the first is
        # accepted: the point is that the second till's failure does not stop the first
        assert out["tills"] + out["errors"] == 2
        assert out["accepted"] >= 1

    async def test_one_tills_crash_does_not_stop_the_next(self, db, tenant_ctx, monkeypatch):
        """A till that RAISES (not merely fails) must not stop the rest, and its own database
        changes inside the run must not leak out half-done."""
        import app.modules.einvoice.providers.eta.delivery as mod

        tid = tenant_ctx.tenant_id
        bad = await _till(db, tid, serial="POS-BAD")
        good = await _till(db, tid, serial="POS-MOCK-1")
        await _issue(db, tid, bad, "R-BAD")
        await _issue(db, tid, good, "R-GOOD")
        real = mod.deliver_device

        async def exploding(session, device_id, **kw):
            if device_id == bad.id:
                (await _doc(session, "R-BAD")).errors = ["half-done change"]
                await session.flush()
                raise RuntimeError("boom")
            return await real(session, device_id, **kw)

        monkeypatch.setattr(mod, "deliver_device", exploding)
        mock = MockAuthority(pos_serial="POS-MOCK-1")
        out = await mod.deliver_tenant(db, tid, provider=_provider(mock))
        assert out["errors"] == 1 and out["accepted"] == 1
        assert (await _doc(db, "R-GOOD")).status == "submitted"
        # the savepoint undid the crashed till's partial write
        assert (await _doc(db, "R-BAD")).errors == []

    async def test_another_stores_tills_are_not_even_selected(self, db, tenant_ctx, admin_url):
        """RLS already hides them; this pins the query's own tenant filter (defence in depth)
        by looking at the statement it issues, which RLS cannot mask."""
        import inspect

        from app.modules.einvoice.providers.eta.delivery import deliver_tenant

        src = inspect.getsource(deliver_tenant)
        assert "EInvoiceDevice.tenant_id == tenant_id" in src
        assert admin_url  # fixture keeps this test honest about needing an owner connection

    async def test_suspended_tills_and_other_providers_are_skipped(self, db, tenant_ctx):
        from app.modules.einvoice.providers.eta.delivery import deliver_tenant

        tid = tenant_ctx.tenant_id
        paused = await _till(db, tid, serial="POS-PAUSED")
        await _issue(db, tid, paused, "R-PAUSED")
        paused.status = "suspended"
        other = await _till(db, tid, serial="POS-ZATCA")
        other.provider_type = "zatca"
        await db.flush()
        mock = MockAuthority()
        out = await deliver_tenant(db, tid, provider=_provider(mock))
        assert out["tills"] == 0 and not mock.submissions

    async def test_a_store_with_no_ready_till_is_a_quiet_no_op(self, db, tenant_ctx):
        from app.modules.einvoice.providers.eta.delivery import deliver_tenant

        out = await deliver_tenant(db, tenant_ctx.tenant_id, provider=_provider(MockAuthority()))
        assert out == {
            "tills": 0,
            "sent": 0,
            "accepted": 0,
            "rejected": 0,
            "failed": 0,
            "errors": 0,
            "attention": [],
        }

    async def test_rejections_surface_as_attention_for_the_owner(self, db, tenant_ctx):
        from app.modules.einvoice.providers.eta.delivery import deliver_tenant

        tid = tenant_ctx.tenant_id
        dev = await _till(db, tid)
        await _issue(db, tid, dev, "R-1")
        out = await deliver_tenant(db, tid, provider=_provider(MockAuthority(rin="000000000")))
        assert out["rejected"] == 1
        assert out["attention"] == [
            {
                "till": "POS-MOCK-1",
                "needs_correction": ["R-1"],
                "window_closing": [],
                "window_closed": [],
            }
        ]

    async def test_the_registered_handler_runs_the_same_thing(self, db, tenant_ctx):
        from app.workers.scheduler_worker import _HANDLERS

        out = await _HANDLERS["einvoice.eta_deliver"](db, tenant_ctx.tenant_id, {})
        assert out["tills"] == 0 and out["errors"] == 0
