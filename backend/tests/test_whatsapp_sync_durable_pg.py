"""The one-shot sync reservation, proven on a real database instead of a fake session.

Meta allows ONE ``POST /{phone-number-id}/smb_app_data`` per sync kind per connection. The
reservation therefore commits in its own transaction before the call, so a crash between "sent" and
"answered" leaves evidence rather than a clean slate that invites a second request. Every existing
test of that path used a fake session, which never enters the durable branch at all — so the
property the design exists for was never actually executed.

These run against Postgres in CI (they skip without ``DATABASE_URL_APP``). The
``app_sessions_on_test_connection`` fixture binds the app's own session factory to the test
connection: the durable session must be a real, separate session, but a second
CONNECTION could not see this test's rows, and a second event loop could not run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.core.db import bind_tenant
from app.modules.conversations import whatsapp_sync
from app.modules.conversations.models import WhatsAppSyncRun
from app.modules.platform.models import Integration

NUMBER = "456"
EPOCH = "2026-11-24T00:00:00+00:00"
ONBOARDED = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
NOW = ONBOARDED + timedelta(minutes=30)


async def _channel(session, tenant_id) -> Integration:
    integration = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider="whatsapp",
        kind="channel",
        config={
            "phone_number_id": NUMBER,
            "waba_id": "1001",
            "onboarding_mode": "coexistence",
            "coexistence_status": "verified",
            "coexistence_verified_at": EPOCH,
        },
        credentials={},
        status="active",
    )
    session.add(integration)
    await session.flush()
    return integration


def _ask(**overrides):
    kwargs = {
        "phone_number_id": NUMBER,
        "waba_id": "1001",
        "epoch": EPOCH,
        "onboarding_completed_at": ONBOARDED,
        "sync_type": whatsapp_sync.WHATSAPP_SYNC_CONTACTS,
        "token": "tok",
        "http": httpx.AsyncClient(),
        "now": NOW,
    }
    kwargs.update(overrides)
    return kwargs


async def _row(session, tenant_id, *, sync_type=whatsapp_sync.WHATSAPP_SYNC_CONTACTS):
    return (
        await session.execute(
            select(WhatsAppSyncRun).where(
                WhatsAppSyncRun.tenant_id == tenant_id,
                WhatsAppSyncRun.phone_number_id == NUMBER,
                WhatsAppSyncRun.sync_type == sync_type,
                WhatsAppSyncRun.onboarding_epoch == EPOCH,
            )
        )
    ).scalar_one_or_none()


async def test_the_reservation_is_visible_before_meta_is_called(
    tenant_ctx, app_sessions_on_test_connection, monkeypatch
) -> None:
    """The whole point of the separate transaction: the row exists FIRST."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _channel(session, tenant_id)
    seen: dict = {}

    async def _post(_http, *, phone_number_id, token, sync_type):
        # Read it back through the app's own factory, at the instant of the call.
        async with app_sessions_on_test_connection() as other:
            await bind_tenant(other, tenant_id)
            row = await _row(other, tenant_id, sync_type=sync_type)
            seen["state"] = row.state if row else None
            seen["request_id"] = row.request_id if row else "missing"
        return "req-1"

    monkeypatch.setattr(whatsapp_sync, "post_sync_request", _post)
    run = await whatsapp_sync.request_sync(session, tenant_id, **_ask())

    assert seen == {"state": "dispatching", "request_id": None}
    assert run.state == "requested"
    assert run.request_id == "req-1"


async def test_a_crash_after_meta_accepted_does_not_erase_the_reservation(
    tenant_ctx, app_sessions_on_test_connection, monkeypatch
) -> None:
    """Meta may have the request; the row must keep saying "a request may exist"."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _channel(session, tenant_id)

    async def _post(_http, **_kwargs):
        return "req-accepted"

    real_get_run = whatsapp_sync._get_run
    calls = {"n": 0}

    async def _get_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # the post-response commit: the process dies here
            raise RuntimeError("process died before the answer was stored")
        return await real_get_run(*args, **kwargs)

    monkeypatch.setattr(whatsapp_sync, "post_sync_request", _post)
    monkeypatch.setattr(whatsapp_sync, "_get_run", _get_run)

    with pytest.raises(RuntimeError):
        await whatsapp_sync.request_sync(session, tenant_id, **_ask())

    monkeypatch.setattr(whatsapp_sync, "_get_run", real_get_run)
    row = await _row(session, tenant_id)
    assert row is not None
    assert row.state == "dispatching"
    assert row.request_id is None
    # And nothing may ask Meta again for this connection.
    allowed, reason = whatsapp_sync.may_request(row, NOW, whatsapp_sync.deadline_from(ONBOARDED))
    assert allowed is False
    assert "do not resend" in reason


async def test_a_second_request_reuses_the_reservation_without_calling_meta_again(
    tenant_ctx, app_sessions_on_test_connection, monkeypatch
) -> None:
    """A retry must not spend the merchant's single allowance twice.

    Two REAL concurrent callers cannot be simulated here: every session in this harness shares the
    one test connection (a second caller on the same connection is a transaction-state error, not a
    race). What is asserted is the guarantee that makes the race safe — the second request reads the
    open reservation and reuses its request id instead of posting to Meta again — plus the DB-level
    one-open-run-per-number constraint that rejects a duplicate insert.
    """
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _channel(session, tenant_id)
    posts: list[str] = []

    async def _post(_http, *, phone_number_id, token, sync_type):
        posts.append(phone_number_id)
        return "req-once"

    monkeypatch.setattr(whatsapp_sync, "post_sync_request", _post)

    first = await whatsapp_sync.request_sync(session, tenant_id, **_ask())
    second = await whatsapp_sync.request_sync(session, tenant_id, **_ask())

    assert posts == [NUMBER]
    assert first.request_id == "req-once"
    assert second.request_id == "req-once"
    rows = (
        (
            await session.execute(
                select(WhatsAppSyncRun).where(
                    WhatsAppSyncRun.tenant_id == tenant_id,
                    WhatsAppSyncRun.phone_number_id == NUMBER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_the_durable_session_is_tenant_scoped(
    tenant_ctx, app_sessions_on_test_connection, monkeypatch
) -> None:
    """RLS holds in the separate session: another tenant's binding sees nothing."""
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _channel(session, tenant_id)

    async def _post(_http, **_kwargs):
        return "req-1"

    monkeypatch.setattr(whatsapp_sync, "post_sync_request", _post)
    await whatsapp_sync.request_sync(session, tenant_id, **_ask())

    async with app_sessions_on_test_connection() as other:
        await bind_tenant(other, uuid.uuid4())  # a different shop
        # A superuser/BYPASSRLS role ignores every policy, so the assertion would pass for the
        # wrong reason. CI runs as the app role; a local superuser run is skipped instead.
        bypass = await other.scalar(
            text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user")
        )
        if bypass:
            pytest.skip("RLS is vacuous under a superuser/BYPASSRLS role")
        assert await _row(other, tenant_id) is None
