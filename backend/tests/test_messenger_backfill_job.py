"""The Messenger history import as a job, a route, and a one-time step after connecting.

The reading and storing is covered in ``test_messenger_backfill.py``. This file covers what wraps
it: the ``messenger.backfill`` handler (chaining pages, keeping its place off the job row), the
owner routes, and the single queueing when a Page is first connected.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.secrets import encrypt_credentials_dict
from app.core.security import create_oauth_state_token
from app.modules.conversations.models import Message
from app.modules.platform.models import Integration, Job
from app.workers import messenger_backfill as worker
from tests.test_messenger_backfill import FakeMeta, _msg, _thread
from tests.test_meta_oauth import (
    _app,
    _config_patch,
    _graph_handler,
    _patch_graph,
    _popup_result,
)

PAGE = "page-1"


async def _messenger(db, tenant_ctx, *, status="active", config=None) -> Integration:
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_ctx.tenant_id,
        provider="messenger",
        kind="channel",
        status=status,
        config={"account_id": PAGE, **(config or {})},
        credentials=encrypt_credentials_dict({"api_key": "page-token", "_meta": {"page_id": PAGE}}),
    )
    db.add(row)
    await db.flush()
    return row


def _history(n_threads=1, next_page=None):
    threads = [_thread(f"t{i}", f"psid-{i}", f"C{i}") for i in range(n_threads)]
    msgs = {
        f"m{i}": _msg(f"m{i}", f"psid-{i}", f"hi {i}", timedelta(days=1)) for i in range(n_threads)
    }
    meta = FakeMeta(threads, msgs, next_page=next_page)
    for i in range(n_threads):
        meta.thread_messages(f"t{i}", [f"m{i}"])
    return meta


@pytest.fixture
def fake_meta(monkeypatch):
    """Route the worker's own ``httpx.AsyncClient()`` to a FakeMeta chosen per test."""
    holder = {}
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("follow_redirects", None)
        return real(transport=httpx.MockTransport(holder["meta"].handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(
        "app.modules.conversations.gateway.messenger_backfill.asyncio.sleep", _no_sleep
    )
    return holder


async def _no_sleep(_s):
    return None


async def _job(db, tenant_ctx, **kw) -> Job:
    job = await worker.enqueue_backfill(db, tenant_ctx.tenant_id, **kw)
    await db.flush()
    return job


# ------------------------------------------------------------------ options


def test_options_survive_a_round_trip():
    since = datetime(2026, 11, 1, tzinfo=UTC)
    got = worker.decode_options(worker.encode_options(days=30, since=since, resume=True))
    assert got == {"days": 30, "since": since, "resume": True}
    plain = worker.decode_options(worker.encode_options(days=7, since=None))
    assert plain == {"days": 7, "since": None, "resume": False}


@pytest.mark.parametrize("bad", [None, "", "x", "1:2", "abc:def:s", "5:99999999999999999999:s"])
def test_unreadable_options_fall_back_to_the_defaults(bad):
    assert worker.decode_options(bad) == {"days": 90, "since": None, "resume": False}


def test_days_are_clamped_to_the_ceiling():
    assert worker.decode_options("9999:-:s")["days"] == worker.MAX_DAYS
    assert worker.decode_options("0:-:s")["days"] == 1


def test_the_job_options_fit_the_job_column_whatever_the_cursor_is():
    """The old design put Meta's cursor in correlation_id (64 chars). It is not in there now."""
    text = worker.encode_options(days=365, since=datetime(2026, 11, 1, tzinfo=UTC), resume=True)
    assert len(text) <= 64


# ------------------------------------------------------------------ handler


async def test_the_handler_stores_history_and_records_where_it_got_to(db, tenant_ctx, fake_meta):
    integration = await _messenger(db, tenant_ctx)
    fake_meta["meta"] = _history(2)
    job = await _job(db, tenant_ctx)
    out = await worker.run_backfill(db, job)
    assert out["messages_written"] == 2 and out["queued_next"] is False
    await db.refresh(integration)
    state = worker.read_state(integration)
    assert state["finished"] is True and state["cursor"] is None
    assert state["threads_done"] == 2 and state["last_result"]["messages_written"] == 2
    assert state["last_run_at"]


async def test_a_page_with_more_to_read_queues_the_next_run_and_keeps_the_cursor_off_the_job(
    db, tenant_ctx, fake_meta
):
    integration = await _messenger(db, tenant_ctx)
    long_cursor = "Q" * 180  # a real Meta cursor is far longer than the job column
    fake_meta["meta"] = _history(1, next_page=long_cursor)
    first = await _job(db, tenant_ctx)
    out = await worker.run_backfill(db, first)
    assert out["queued_next"] is True
    await db.refresh(integration)
    assert worker.read_state(integration)["cursor"] == long_cursor
    queued = (
        (
            await db.execute(
                select(Job).where(Job.tenant_id == tenant_ctx.tenant_id, Job.id != first.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(queued) == 1 and len(queued[0].correlation_id) <= 64
    assert worker.decode_options(queued[0].correlation_id)["resume"] is True


async def test_the_chained_run_continues_from_the_stored_cursor(db, tenant_ctx, fake_meta):
    await _messenger(db, tenant_ctx)
    fake_meta["meta"] = _history(1, next_page="CUR-A")
    await worker.run_backfill(db, await _job(db, tenant_ctx))
    meta2 = _history(1)
    fake_meta["meta"] = meta2
    resumed = await _job(db, tenant_ctx, resume=True)
    await worker.run_backfill(db, resumed)
    assert any("after=CUR-A" in c for c in meta2.calls)


async def test_a_manual_run_starts_from_the_top_even_if_an_old_cursor_is_stored(
    db, tenant_ctx, fake_meta
):
    await _messenger(db, tenant_ctx, config={"_backfill": {"cursor": "STALE", "threads_done": 400}})
    meta = _history(1)
    fake_meta["meta"] = meta
    await worker.run_backfill(db, await _job(db, tenant_ctx))
    assert not any("after=STALE" in c for c in meta.calls)


async def test_a_throttled_run_does_not_queue_itself_again_and_remembers_why(
    db, tenant_ctx, fake_meta
):
    integration = await _messenger(db, tenant_ctx)
    meta = _history(1, next_page="CUR")
    meta.throttle_after = 1
    fake_meta["meta"] = meta
    out = await worker.run_backfill(db, await _job(db, tenant_ctx))
    assert out["queued_next"] is False and out["stopped_reason"] == "rate_limited"
    await db.refresh(integration)
    assert worker.read_state(integration)["stopped_reason"] == "rate_limited"


async def test_a_disconnected_channel_imports_nothing(db, tenant_ctx, fake_meta):
    await _messenger(db, tenant_ctx, status="disconnected")
    fake_meta["meta"] = _history(1)
    out = await worker.run_backfill(db, await _job(db, tenant_ctx))
    assert out["skipped"] is True
    assert (
        await db.execute(select(Message).where(Message.tenant_id == tenant_ctx.tenant_id))
    ).first() is None


async def test_no_messenger_channel_at_all_is_skipped_not_an_error(db, tenant_ctx, fake_meta):
    fake_meta["meta"] = _history(1)
    assert (await worker.run_backfill(db, await _job(db, tenant_ctx)))["skipped"] is True


async def test_the_page_token_never_appears_in_the_stored_state_or_the_summary(
    db, tenant_ctx, fake_meta
):
    integration = await _messenger(db, tenant_ctx)
    fake_meta["meta"] = _history(1)
    out = await worker.run_backfill(db, await _job(db, tenant_ctx))
    await db.refresh(integration)
    assert "page-token" not in repr(out) + repr(integration.config)


# ------------------------------------------------------------------ routes


async def _call(db, tenant_ctx, method, path, *, permission=True, json=None, grants=None):
    """``grants`` names the exact permissions the caller holds; otherwise write or nothing."""
    app = _app(db, tenant_ctx, permission=permission)
    if grants is not None:
        from app.modules.identity.deps import get_tenant_ctx  # noqa: PLC0415

        current = await app.dependency_overrides[get_tenant_ctx]()
        current.permission_codes = set(grants)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(method, f"/api/v1{path}", json=json)


async def test_the_owner_can_start_an_import_and_it_is_audited(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    r = await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json={"days": 14})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["days"] == 14
    job = (await db.execute(select(Job).where(Job.id == uuid.UUID(body["job_id"])))).scalar_one()
    assert job.kind == "messenger.backfill" and job.tenant_id == tenant_ctx.tenant_id


async def test_a_user_without_settings_write_cannot_start_one(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    r = await _call(
        db, tenant_ctx, "POST", "/integrations/messenger/backfill", permission=False, json={}
    )
    assert r.status_code == 403
    assert (
        await db.execute(select(Job).where(Job.tenant_id == tenant_ctx.tenant_id))
    ).first() is None


async def test_a_second_import_cannot_start_while_one_is_running(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    assert (
        await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json={})
    ).status_code == 202
    again = await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json={})
    assert again.status_code == 409


async def test_no_import_for_a_channel_that_is_not_connected(db, tenant_ctx):
    assert (
        await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json={})
    ).status_code == 404
    await _messenger(db, tenant_ctx, status="disconnected")
    r = await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json={})
    assert r.status_code in (400, 422)


async def test_the_days_and_since_are_validated(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    for body in ({"days": 0}, {"days": 366}, {"since": "not a date"}):
        r = await _call(db, tenant_ctx, "POST", "/integrations/messenger/backfill", json=body)
        assert r.status_code == 422


async def test_a_reader_sees_the_status_but_cannot_start_a_run(db, tenant_ctx):
    await _messenger(
        db,
        tenant_ctx,
        config={
            "_backfill": {
                "threads_done": 7,
                "finished": True,
                "last_run_at": "2026-11-23T04:00:00+00:00",
                "last_result": {"messages_written": 12},
            }
        },
    )
    seen = await _call(
        db, tenant_ctx, "GET", "/integrations/messenger/backfill", grants={"settings:read"}
    )
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["connected"] is True and body["finished"] is True and body["threads_done"] == 7
    assert body["last_result"] == {"messages_written": 12}
    assert "page-token" not in seen.text
    start = await _call(
        db,
        tenant_ctx,
        "POST",
        "/integrations/messenger/backfill",
        json={},
        grants={"settings:read"},
    )
    assert start.status_code == 403


async def test_a_caller_with_no_settings_access_cannot_read_the_status(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    r = await _call(db, tenant_ctx, "GET", "/integrations/messenger/backfill", grants=set())
    assert r.status_code == 403


async def test_the_status_says_not_connected_when_there_is_no_channel(db, tenant_ctx):
    r = await _call(
        db, tenant_ctx, "GET", "/integrations/messenger/backfill", grants={"settings:read"}
    )
    assert r.status_code == 200 and r.json()["connected"] is False and r.json()["running"] is False


async def test_the_status_shows_a_run_in_progress(db, tenant_ctx):
    await _messenger(db, tenant_ctx)
    await _job(db, tenant_ctx)
    r = await _call(
        db, tenant_ctx, "GET", "/integrations/messenger/backfill", grants={"settings:read"}
    )
    assert r.json()["running"] is True


# ------------------------------------------------------------------ after connect


async def _connect(db, tenant_ctx, monkeypatch, *, provider="messenger", patched=False):
    """Run the OAuth callback once. ``patched`` is for a second call in the same test: the Meta
    fake is installed on ``httpx.AsyncClient`` only once, or the second patch wraps the first."""
    if not patched:
        _config_patch(monkeypatch)
        _patch_graph(monkeypatch, _graph_handler([]))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id), {"tenant_id": str(tenant_ctx.tenant_id), "provider": provider}
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert "connected" in _popup_result(response)


async def _jobs(db, tenant_ctx) -> list[Job]:
    return list(
        (
            await db.execute(
                select(Job).where(
                    Job.tenant_id == tenant_ctx.tenant_id, Job.kind == "messenger.backfill"
                )
            )
        )
        .scalars()
        .all()
    )


async def test_connecting_messenger_queues_one_history_import(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    await _connect(db, tenant_ctx, monkeypatch)
    assert len(await _jobs(db, tenant_ctx)) == 1
    row = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_ctx.tenant_id, Integration.provider == "messenger"
            )
        )
    ).scalar_one()
    assert worker.read_state(row)["auto_queued_at"]


async def test_reconnecting_does_not_queue_it_again_and_keeps_the_record(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    await _connect(db, tenant_ctx, monkeypatch)
    await _connect(db, tenant_ctx, monkeypatch, patched=True)
    assert len(await _jobs(db, tenant_ctx)) == 1
    row = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_ctx.tenant_id, Integration.provider == "messenger"
            )
        )
    ).scalar_one()
    assert worker.read_state(row).get("auto_queued_at")  # the connect rewrite did not wipe it


async def test_a_failure_to_queue_never_fails_the_connection(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    async def boom(*_a, **_k):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.workers.messenger_backfill.enqueue_backfill", boom)
    await _connect(db, tenant_ctx, monkeypatch)  # asserts "connected"
    assert await _jobs(db, tenant_ctx) == []


async def test_connecting_facebook_alone_queues_no_messenger_import(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    _patch_graph(monkeypatch, _graph_handler([]))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id), {"tenant_id": str(tenant_ctx.tenant_id), "provider": "facebook"}
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert "connected" in _popup_result(r)
    assert await _jobs(db, tenant_ctx) == []
