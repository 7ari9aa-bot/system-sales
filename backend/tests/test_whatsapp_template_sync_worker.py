"""The periodic template sync: who is visited, who is skipped, and that one failure is isolated."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.workers import whatsapp_template_sync as w

T1, T2, T3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _patch(monkeypatch, tenants, one):
    async def lister():
        return tenants

    monkeypatch.setattr(w, "_tenants_with_meta_templates", lister)
    monkeypatch.setattr(w, "sync_one_tenant", one)


@pytest.mark.asyncio
async def test_every_store_with_a_template_is_visited_and_changes_are_summed(monkeypatch):
    seen = []

    async def one(tenant_id, **kw):
        seen.append(tenant_id)
        return {"changed": ["a", "b"] if tenant_id == T1 else ["c"]}

    _patch(monkeypatch, [T1, T2], one)
    assert await w.sweep_template_status() == 3
    assert seen == [T1, T2]


@pytest.mark.asyncio
async def test_one_store_failing_does_not_stop_the_others(monkeypatch):
    seen = []

    async def one(tenant_id, **kw):
        seen.append(tenant_id)
        if tenant_id == T2:
            raise RuntimeError("Meta is down for this store")
        return {"changed": ["x"]}

    _patch(monkeypatch, [T1, T2, T3], one)
    assert await w.sweep_template_status() == 2
    assert seen == [T1, T2, T3]


@pytest.mark.asyncio
async def test_a_store_that_is_not_connected_counts_for_nothing(monkeypatch):
    async def one(tenant_id, **kw):
        return None

    _patch(monkeypatch, [T1], one)
    assert await w.sweep_template_status() == 0


@pytest.mark.asyncio
async def test_no_stores_means_no_work(monkeypatch):
    async def one(tenant_id, **kw):
        raise AssertionError("must not be called")

    _patch(monkeypatch, [], one)
    assert await w.sweep_template_status() == 0


def test_only_states_meta_can_still_change_are_watched():
    assert set(w.WATCHED_STATUSES) == {"submitted", "approved", "paused"}
    assert not {"draft", "rejected", "archived"} & set(w.WATCHED_STATUSES)


def test_the_sweep_is_registered_to_run_every_fifteen_minutes():
    from app.workers.scheduler_worker import GLOBAL_SWEEPERS

    interval, fn = GLOBAL_SWEEPERS["whatsapp.template_status_sync"]
    assert interval == timedelta(minutes=15)
    assert callable(fn)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Session:
    """Answers the worker's queries and keeps the SQL it was asked, so its filter can be checked."""

    def __init__(self, answers, log):
        self._answers = answers
        self._log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return self

    async def execute(self, stmt):
        self._log.append(stmt)
        return _Rows(self._answers.pop(0))


def _factory(answers, log):
    return lambda: _Session(answers, log)


@pytest.mark.asyncio
async def test_a_store_is_picked_only_for_a_whatsapp_template_that_lives_on_meta(monkeypatch):
    log = []
    # 2 stores listed; the first has a matching template, the second has none.
    answers = [[T1, T2], [uuid.uuid4()], []]
    monkeypatch.setattr(w, "SessionLocal", _factory(answers, log))

    async def bind(session, tenant_id):
        return None

    monkeypatch.setattr(w, "bind_tenant", bind)
    assert await w._tenants_with_meta_templates() == [T1]

    sql = str(log[1].compile(compile_kwargs={"literal_binds": True}))
    assert "provider = 'whatsapp'" in sql
    assert "category IS NOT NULL" in sql
    assert "category != ''" in sql
    for status in ("submitted", "approved", "paused"):
        assert f"'{status}'" in sql
    assert "'draft'" not in sql and "'rejected'" not in sql and "'archived'" not in sql
    assert "LIMIT 1" in sql.upper() or "LIMIT" in sql.upper()
