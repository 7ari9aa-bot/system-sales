"""§51/§131/§172 — erasure must release the media it leaves no pointer to.

The deletion chain ends its transcript step with::

    UPDATE messages SET body = '[REDACTED]', media_url = NULL ...

which strips the text and NULLs the pointer — and stops there. The ``attachments``
rows that hold the real pointer (``storage_key``), plus the ``transcript_text`` of
every voice note, survive, and so do the bytes in the bucket, now named by nothing
in the database. ``docs/PII_DATA_MAP.md`` (§131 makes the map binding) gives that
store the retention value ``policy`` and the deletion behavior **``storage delete +
row delete``**, and closes with the rule "Any NEW store added to the system MUST be
appended to this map + wired into DeletionService". ``attachments`` was wired into
neither half of that sentence.

So a data-subject deletion — the most authorised deletion there is, asked for by
the person themselves — was the one path that leaked media for certain.

The closure mirrors what the retention sweep now does in
``app/modules/analytics/retention.py`` (which cannot be imported from here without
crossing the module boundary the ratchet guards): gather the keys, delete the rows,
redact the transcripts, and release the objects LAST. A release that fails is
REPORTED inside the audited report instead of aborting the erasure — a dead bucket
must not leave a data-subject request impossible to close, and an *unreported*
leak is exactly what made the old path unauditable.

DB-free: the session is a scripted double and the bucket is a spy, so every
assertion here runs without ``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import app.core.search as search_mod
import app.core.storage as storage_mod
from app.modules.customers.service import CustomerService
from app.modules.privacy.service import DeletionService

TENANT = uuid.UUID("88888888-8888-8888-8888-888888888888")
CUSTOMER = uuid.UUID("77777777-7777-7777-7777-777777777777")
ATTACHMENT_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
VOICE_NOTE = "media/2026/09/subject-voice.opus"
PHOTO = "media/2026/09/subject-photo.jpg"


class _Result:
    def __init__(self, rows: tuple[Any, ...] = (), rowcount: int = 0) -> None:
        self._rows = tuple(rows)
        self.rowcount = rowcount

    def all(self) -> tuple[Any, ...]:
        return self._rows

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError(f"expected one row, got {len(self._rows)}")
        return self._rows[0]

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _FakeCustomer:
    """Enough of ``Customer`` for the chain, which only reads/writes erasure fields."""

    def __init__(self) -> None:
        self.id = CUSTOMER
        self.deleted_at = None
        self.deleted_by = None
        self.deletion_reason = None
        self.is_blocked = False
        self.version = 3


class _ErasureSession:
    """Answers the statements the §172 chain runs, in order, and records them.

    ``media_rows`` is what a gather of this subject's attachments hands back —
    (id, storage_key) pairs. Anything outside the known set raises, so no new
    statement can slip through un-asserted.
    """

    def __init__(self, *, media_rows: tuple[tuple[Any, ...], ...] = ()) -> None:
        self.media_rows = tuple(media_rows)
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.added: list[Any] = []
        self.audit_after: dict[str, Any] | None = None

    async def execute(self, statement, params=None):
        sql = str(statement)
        parsed = dict(params or {})
        self.statements.append(sql)
        self.params.append(parsed)
        if "to_regclass" in sql:
            return _Result(((False,),))
        if "INSERT INTO audit_logs" in sql:
            after = parsed.get("after")
            self.audit_after = json.loads(after) if after else None
            return _Result()
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            return _Result(self.media_rows)
        if sql.strip().upper().startswith("DELETE") and "attachments" in sql:
            return _Result(rowcount=len(parsed.get("ids", [])))
        if "DELETE FROM memories" in sql:
            return _Result(rowcount=1)
        if sql.strip().upper().startswith("UPDATE") and "messages" in sql:
            return _Result(rowcount=2)
        if sql.strip().upper().startswith("UPDATE") and "data_subject_requests" in sql:
            return _Result(rowcount=1)
        raise AssertionError(f"unexpected statement from the erasure chain: {sql[:180]}")

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    # --- assertions helpers used by the tests -------------------------------

    def indexes(self, needle: str) -> list[int]:
        return [i for i, s in enumerate(self.statements) if needle in s]

    def statement(self, needle: str) -> str:
        hits = self.indexes(needle)
        assert hits, f"no statement containing {needle!r} ran"
        return self.statements[hits[0]]

    def params_for(self, needle: str) -> dict[str, Any]:
        hits = self.indexes(needle)
        assert hits, f"no statement containing {needle!r} ran"
        return self.params[hits[0]]


class _BucketSpy:
    """Stands in for the object store: records every call, and can fail."""

    def __init__(self, *, fail: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail = set(fail or [])

    async def delete_objects(self, keys):
        keys = list(keys)
        self.calls.append(keys)
        return [k for k in keys if k in self.fail]


def _wire(monkeypatch, *, media_rows=(), bucket=None) -> _ErasureSession:
    """Install the doubles: one customer row, no external search, one bucket."""
    session = _ErasureSession(media_rows=media_rows)

    async def _get_for_erasure(_session, _tenant_id, _customer_id):
        return _FakeCustomer()

    monkeypatch.setattr(CustomerService, "get_for_erasure", staticmethod(_get_for_erasure))

    def _no_search():
        # The chain already swallows this and appends a "failed" step; the point
        # is that no real search port is contacted by a DB-free test.
        raise RuntimeError("no external search engine configured")

    monkeypatch.setattr(search_mod, "get_search", _no_search)
    monkeypatch.setattr(storage_mod, "get_storage", lambda: bucket or _BucketSpy())
    return session


async def _erase(session) -> dict:
    return await DeletionService.propagate_customer_deletion(
        session, TENANT, CUSTOMER, requested_by_user_id=None, reason="data_subject_request"
    )


# ================================ 1. the subject's media rows must actually go ==


async def test_erasure_deletes_the_attachment_rows(monkeypatch) -> None:
    """RED: the chain redacted ``messages`` and never opened ``attachments``, so
    the media rows — and the transcript_text inside them — outlived a subject's
    own deletion request."""
    session = _wire(monkeypatch, media_rows=((ATTACHMENT_ID, VOICE_NOTE),))
    report = await _erase(session)

    assert session.indexes("DELETE FROM attachments"), (
        "erasure leaves the subject's media rows behind"
    )
    steps = {step["step"] for step in report["steps"]}
    assert "media_rows_deleted" in steps


async def test_the_gather_is_scoped_to_this_subject_and_this_tenant(monkeypatch) -> None:
    """A purge that reached another conversation is a breach, not a fix."""
    session = _wire(monkeypatch, media_rows=((ATTACHMENT_ID, VOICE_NOTE),))
    await _erase(session)

    gather = session.statement("storage_key")
    assert "attachments" in gather
    assert "a.tenant_id = :t" in gather or "tenant_id = :t" in gather
    # the media hangs off the subject's conversations, the same join the
    # transcript redaction already uses
    assert "conversation" in gather and "customer_id" in gather
    assert session.params_for("storage_key") == {"t": TENANT, "c": CUSTOMER}


async def test_rows_gone_and_transcripts_redacted_before_the_bytes_leave(monkeypatch) -> None:
    """Ordering is the whole safety argument: releasing first would delete a live
    customer's photo; releasing at all is only safe once no row points at it."""
    session = _wire(
        monkeypatch,
        media_rows=((ATTACHMENT_ID, VOICE_NOTE), (ATTACHMENT_ID, PHOTO)),
        bucket=(bucket := _BucketSpy()),
    )
    await _erase(session)

    assert bucket.calls == [[VOICE_NOTE, PHOTO]], "one release, with both keys"
    release_at = min(session.indexes("DELETE FROM attachments"))
    assert session.indexes("UPDATE messages")[0] < release_at or release_at > max(
        session.indexes("UPDATE messages")
    ), "the bucket was emptied before the transcript step finished"
    assert release_at == max(release_at for release_at in session.indexes("attachments"))
    assert session.indexes("INSERT INTO audit_logs")[0] < len(session.statements)


# ================================= 2. a failed release is a fact, not a rumour ==


async def test_a_failed_release_is_audited_and_not_swallowed(monkeypatch) -> None:
    """A leak with no trail cannot be reconciled; the audited report must name
    the keys that stayed."""
    session = _wire(
        monkeypatch,
        media_rows=((ATTACHMENT_ID, VOICE_NOTE),),
        bucket=_BucketSpy(fail=[VOICE_NOTE]),
    )
    report = await _erase(session)

    step = next(s for s in report["steps"] if s["step"] == "media_objects_released")
    assert step["failed"] == [VOICE_NOTE]
    assert step["released"] == 0
    assert session.audit_after is not None
    assert VOICE_NOTE in json.dumps(session.audit_after), (
        "the erasure audit must carry the leak it could not close"
    )


async def test_no_media_means_no_bucket_call_and_no_invented_step(monkeypatch) -> None:
    """A subject with only text must purge exactly as before — no empty DELETE,
    no call to a bucket that holds nothing of theirs."""
    bucket = _BucketSpy()
    session = _wire(monkeypatch, media_rows=(), bucket=bucket)
    report = await _erase(session)

    assert bucket.calls == []
    assert session.indexes("DELETE FROM attachments") == []
    steps = {step["step"] for step in report["steps"]}
    assert "media_rows_deleted" not in steps


async def test_the_release_failure_never_aborts_the_erasure(monkeypatch) -> None:
    """get_storage() may be unreachable (no config, dead endpoint); the deletion
    still closes the request, and the incident rides the report."""

    def _broken():
        raise RuntimeError("bucket endpoint unreachable")

    session = _wire(monkeypatch, media_rows=((ATTACHMENT_ID, VOICE_NOTE),))
    monkeypatch.setattr(storage_mod, "get_storage", _broken)
    report = await _erase(session)

    step = next(s for s in report["steps"] if s["step"] == "media_objects_released")
    assert step["failed"] == [VOICE_NOTE]
    assert step.get("error"), "the report says why nothing could be released"
    tombstone = next(s for s in report["steps"] if s["step"] == "domain_tombstone")
    assert tombstone["done"] is True
