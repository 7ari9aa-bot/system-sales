"""§52 — the stores the ✅ never reached: media, and a marketing lead.

Why this file exists
--------------------
``docs/COMPLIANCE_MATRIX.md`` marks §51-52 complete on the strength of a sweep
that honours a tenant-chosen horizon for ``messages``, ``webhook_events`` and
``ai_usage``. §52 does not stop at three classes: it names
``Messages / Attachments / Audit / AI Usage / Logs / Analytics / Backups`` and
says EVERY data class carries a policy that a worker executes. And
``docs/PII_DATA_MAP.md`` — the map this repository treats as binding (§131) —
gives ``attachments`` the retention value ``policy`` and the deletion behavior
``storage delete + row delete``.

Neither promise is kept:

* ``attachments`` (image/voice/video bytes in the bucket + ``transcript_text``)
  is in no allowlist, so no merchant can state a horizon for it and the sweep
  never opens the table. Worse, the shipped ``messages`` purge takes those rows
  with it by ``ON DELETE CASCADE`` (``49303e2e2dd0``: ``attachments.message_id``
  -> ``messages.id`` CASCADE) and deletes the ROW while the OBJECT stays in the
  bucket forever — the purge destroys the only pointer to the PII it was meant
  to remove. So the ✅ for ``messages`` is a media-leak generator.
* ``leads`` holds a raw name/phone/email of a person who may never have become a
  customer (``customer_id`` is nullable), and appears nowhere in the map, the
  allowlist or the sweep.

The closure per store:

- ``attachments``: a choosable horizon, deleted by ROW, and the object released
  afterwards — ordered so a live row can never point at a deleted object (a lost
  object is data loss; a leaked one is a retention gap an audit row can name).
- ``messages``: must not orphan media — the child rows and their objects leave
  with the batch, before the parent DELETE.
- ``leads``: a choosable horizon, plain row purge. A converted lead's PII lives
  on in ``customers`` (out of retention's reach by design), so the lead row is a
  second copy and may age out.
- Everything the sweep must NOT reach: named in :data:`REFUSED_DATA_CLASSES`
  with the rule that keeps it, so "unreachable" and "deliberately unreachable"
  stop being the same line in the same file. A store the map hands to the
  retention worker but that is in neither set is a hole, and
  :func:`_map_stores_handed_to_the_worker` makes the map executable about it.

DB-free: the session is a scripted double and the object release is a spy, so
every assertion below runs everywhere. Nothing here needs
``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.analytics import retention

MESSAGES = "messages"
ATTACHMENTS = "attachments"
LEADS = "leads"

TENANT = uuid.UUID("88888888-8888-8888-8888-888888888888")
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

#: The map is a document; this test reads it as a contract. Its "EventLog" row
#: names the table ``event_log``.
_MAP_ALIASES = {"eventlog": "event_log"}
_MAP_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "PII_DATA_MAP.md"


# ------------------------------------------------------------- the doubles ---


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


class _MediaSession:
    """Answers the statements a media-bearing purge may run, in order.

    ``media_rows`` is what the gather SELECT hands back — (id, storage_key) pairs
    — and each gathered batch is deleted by explicit id list, so the double can
    assert the purge never deletes a row it has no key for.
    """

    def __init__(
        self,
        *,
        tenant_active: bool = True,
        policy: tuple[int | None, str | None] | None = (365, "active"),
        media_rows: tuple[tuple[Any, ...], ...] = (),
        rowcounts: list[int] | None = None,
    ) -> None:
        self.tenant_active = tenant_active
        self.policy = policy
        self.media_rows = tuple(media_rows)
        self.rowcounts = list(rowcounts or [])
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.audit_writes = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        parsed = dict(params or {})
        self.statements.append(sql)
        self.params.append(parsed)
        if "FROM tenants" in sql:
            return _Result(((self.tenant_active,),))
        if "INSERT INTO audit_logs" in sql:
            self.audit_writes += 1
            return _Result()
        if "retention_policies" in sql and "data_class" in parsed:
            return _Result((self.policy,) if self.policy is not None else ())
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            return _Result(self.media_rows)
        if sql.strip().upper().startswith("DELETE"):
            return _Result(rowcount=self.rowcounts.pop(0) if self.rowcounts else 0)
        raise AssertionError(f"unexpected statement from the purge path: {sql[:160]}")


class _ReleaseSpy:
    """Stands in for the bucket: records WHEN it was called, and can fail."""

    def __init__(self, *, fail: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail = set(fail or [])

    async def __call__(self, keys):
        keys = list(keys)
        self.calls.append(keys)
        return [k for k in keys if k in self.fail]


def _map_rows() -> list[list[str]]:
    rows = []
    for line in _MAP_PATH.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] and not set(cells[0]) <= {"-", " "}:
            rows.append(cells)
    return rows


def _map_stores_handed_to_the_worker() -> set[str]:
    """The map's own §131 claim: which stores the retention worker deletes."""
    out: set[str] = set()
    for cells in _map_rows():
        if "retention worker" in cells[4]:
            label = re.sub(r"[`*]", "", cells[0]).strip().lower()
            out.add(_MAP_ALIASES.get(label, label))
    return out


# =============================== 1. the two stores must be choosable at all ===


def test_attachments_is_a_data_class_a_tenant_can_choose() -> None:
    """RED first: the map promised this store a policy and no surface could give
    it one, so the media a customer sent has no horizon at all."""
    assert ATTACHMENTS in retention.ROW_LEVEL_DATA_CLASSES
    assert ATTACHMENTS in retention.CHOOSABLE_DATA_CLASSES
    spec = retention.ROW_LEVEL_DATA_CLASSES[ATTACHMENTS]
    assert spec.table == ATTACHMENTS
    assert spec.ts_column == "created_at"


def test_a_lead_is_a_data_class_a_tenant_can_choose() -> None:
    """A lead is a named person's phone and email, held without their becoming a
    customer — the least defensible unpurged store in the schema."""
    assert LEADS in retention.ROW_LEVEL_DATA_CLASSES
    assert LEADS in retention.CHOOSABLE_DATA_CLASSES
    assert retention.ROW_LEVEL_DATA_CLASSES[LEADS].ts_column == "created_at"


def test_the_new_stores_are_offered_no_invented_horizon() -> None:
    """The module's own rule: a store the map gives no duration for gets NO
    pre-filled default, so the merchant has to state the number."""
    assert ATTACHMENTS not in retention.DEFAULT_RETENTION_DAYS
    assert LEADS not in retention.DEFAULT_RETENTION_DAYS


def test_the_map_is_an_executable_contract() -> None:
    """Every store the map hands to the retention worker must be purged or
    refused OUT LOUD. Silence is what let a ✅ cover three of seven classes."""
    purged = set(retention.ROW_LEVEL_DATA_CLASSES)
    refused = set(retention.REFUSED_DATA_CLASSES)
    handed_over = _map_stores_handed_to_the_worker()
    assert handed_over, "the map must be readable as a contract"
    for store in sorted(handed_over):
        assert (store in purged) != (store in refused), (
            f"{store}: neither purged nor deliberately refused"
        )


def test_a_refusal_names_the_rule_behind_it() -> None:
    """"Not now" and "never, because §57" are different answers; only the second
    one earns a place outside the allowlist."""
    for store, reason in retention.REFUSED_DATA_CLASSES.items():
        assert "§" in reason, f"{store}: a refusal with no rule behind it"
        assert store not in retention.ROW_LEVEL_DATA_CLASSES
        assert store not in retention.CHOOSABLE_DATA_CLASSES
    # §57 legal retention and §152 replay are the two named keeps.
    assert "audit_logs" in retention.REFUSED_DATA_CLASSES
    assert "event_log" in retention.REFUSED_DATA_CLASSES


# ============================================ 2. a media purge releases bytes ==


async def test_purging_an_attachment_releases_its_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    session = _MediaSession(
        policy=(365, "active"),
        media_rows=((uuid.uuid4(), "media/aaa.jpg"), (uuid.uuid4(), "media/bbb.ogg")),
        rowcounts=[2],
    )

    result = await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)

    assert result["deleted"] == 2
    assert release.calls == [["media/aaa.jpg", "media/bbb.ogg"]], release.calls
    assert result["media_objects_released"] == 2
    assert result["media_objects_failed"] == []


async def test_the_objects_leave_only_after_their_rows_are_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The order is the whole safety argument: release first and a rollback
    leaves a live row pointing at a deleted object (data loss); release last and
    the worst case is a leaked object that the audit row can name."""
    order: list[str] = []

    async def spy_release(keys):
        order.append(f"release:{len(list(keys))}")
        return []

    monkeypatch.setattr(retention, "release_media_objects", spy_release)

    class _Logging(_MediaSession):
        async def execute(self, statement, params=None):
            sql = str(statement).strip().upper()
            if sql.startswith("DELETE"):
                order.append("delete")
            elif "storage_key" in str(statement):
                order.append("gather")
            return await super().execute(statement, params)

    session = _Logging(
        policy=(365, "active"),
        media_rows=((uuid.uuid4(), "media/one.jpg"),),
        rowcounts=[1],
    )
    await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)
    assert order == ["gather", "delete", "release:1"], order


async def test_a_media_batch_is_gathered_by_key_and_deleted_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A media row must never die by an unbounded predicate: the DELETE carries
    exactly the ids whose keys were read, plus the tenant predicate."""
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    key_a, key_b = uuid.uuid4(), uuid.uuid4()
    session = _MediaSession(
        policy=(90, "active"),
        media_rows=((key_a, "media/a.jpg"), (key_b, "media/b.jpg")),
        rowcounts=[2],
    )
    await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)

    deletes = [s for s in session.statements if s.strip().upper().startswith("DELETE")]
    assert len(deletes) == 1, deletes
    assert "FROM attachments" in deletes[0]
    assert "id = ANY(CAST(:ids AS uuid[]))" in deletes[0], deletes[0]
    assert "tenant_id = :tenant_id" in deletes[0]
    delete_index = session.statements.index(deletes[0])
    assert session.params[delete_index]["ids"] == [str(key_a), str(key_b)]
    assert release.calls == [["media/a.jpg", "media/b.jpg"]]
    gathers = [s for s in session.statements if s.strip().upper().startswith("SELECT")]
    assert any("LIMIT" in s for s in gathers), "the gathered batch must be bounded"
    assert any("created_at < :cutoff" in s for s in gathers)


async def test_a_failed_release_is_reported_and_audited_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An object the bucket refused to delete is still customer PII past its
    horizon; the sweep's own answer must say so and the audit row must carry it.
    """
    release = _ReleaseSpy(fail=["media/b.jpg"])
    monkeypatch.setattr(retention, "release_media_objects", release)
    audit = _AuditRecorder()
    monkeypatch.setattr(retention, "write_audit_row", audit)
    session = _MediaSession(
        policy=(365, "active"),
        media_rows=((uuid.uuid4(), "media/a.jpg"), (uuid.uuid4(), "media/b.jpg")),
        rowcounts=[2],
    )

    result = await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)

    assert result["media_objects_failed"] == ["media/b.jpg"]
    assert result["media_objects_released"] == 1
    assert audit.kwargs[0]["after"]["media_objects_failed"] == ["media/b.jpg"]


class _AuditRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []

    async def __call__(self, session, tenant_id, actor, action, resource, resource_id, **kw):
        self.calls.append((tenant_id, actor, action, resource, resource_id))
        self.kwargs.append(kw)


async def test_a_refused_attachment_purge_touches_no_rows_and_no_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same consent gate governs media: no chosen horizon, no deletion —
    and no object leaves the bucket either."""
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    for policy, reason in (
        (None, retention.BLOCKED_NO_CHOSEN_POLICY),
        ((365, "paused"), retention.BLOCKED_NO_CHOSEN_POLICY),
        ((0, "active"), retention.BLOCKED_NO_POSITIVE_HORIZON),
    ):
        session = _MediaSession(policy=policy, media_rows=())
        result = await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)
        assert result["skipped_reason"] == reason
        assert result["deleted"] == 0
        assert not [s for s in session.statements if s.strip().upper().startswith("DELETE")]
    assert release.calls == []


async def test_an_in_flight_attachment_survives_the_purge() -> None:
    """§33-35: a media row still being downloaded, scanned or transcribed is a
    pipeline in progress, not cold data — the same reasoning §130 applies to an
    unreconciled message."""
    session = _MediaSession(policy=(365, "active"), media_rows=(), rowcounts=[0])
    await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)
    sql = next(s for s in session.statements if "FROM attachments" in s)
    assert "scan_status" in sql and "processing_status" in sql, sql
    assert "transcription_status" in sql, sql


# ================================= 3. the messages purge must not orphan media ==


async def test_purging_messages_releases_their_media_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped defect: ``attachments.message_id`` is ``ON DELETE CASCADE``, so
    today a messages purge deletes the row and leaves the bytes — permanently
    invisible. The child rows must leave, with their keys in hand, BEFORE the
    parent DELETE takes the pointer away."""
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    child_id = uuid.uuid4()
    # rowcounts in statement order: the child DELETE attachments, then the parent
    # DELETE messages.
    session = _MediaSession(
        policy=(365, "active"),
        media_rows=((child_id, "media/voice.ogg"),),
        rowcounts=[1, 3],
    )

    result = await retention.purge_row_store(session, TENANT, MESSAGES, now=NOW)

    assert result["deleted"] == 3
    assert result["media_rows_deleted"] == 1
    assert release.calls == [["media/voice.ogg"]], release.calls
    child_delete = next(
        i
        for i, s in enumerate(session.statements)
        if s.strip().upper().startswith("DELETE") and "attachments" in s
    )
    parent_delete = next(
        i
        for i, s in enumerate(session.statements)
        if s.strip().upper().startswith("DELETE") and "FROM messages" in s
    )
    assert child_delete < parent_delete, "the cascade must never win the race"


async def test_a_message_with_no_media_purges_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing here may make the shipped path delete less: no keys gathered, no
    child DELETE issued, the parent statement still LIMIT-shaped."""
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    session = _MediaSession(policy=(365, "active"), media_rows=(), rowcounts=[7])

    result = await retention.purge_row_store(session, TENANT, MESSAGES, now=NOW)

    assert result["deleted"] == 7
    child_deletes = [
        s
        for s in session.statements
        if s.strip().upper().startswith("DELETE") and "attachments" in s
    ]
    assert child_deletes == [], "an empty batch must not issue a child DELETE"
    parent = next(s for s in session.statements if "FROM messages" in s)
    assert "LIMIT" in parent and "tenant_id = :tenant_id" in parent
    assert release.calls == []


# ================================================= 4. leads: a plain row purge ==


async def test_a_lead_ages_out_on_the_horizon_the_tenant_stated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _ReleaseSpy()
    monkeypatch.setattr(retention, "release_media_objects", release)
    session = _MediaSession(policy=(180, "active"), media_rows=(), rowcounts=[4])

    result = await retention.purge_row_store(session, TENANT, LEADS, now=NOW)

    assert result["deleted"] == 4
    sql = next(s for s in session.statements if s.strip().upper().startswith("DELETE"))
    assert "FROM leads" in sql
    assert "created_at < :cutoff" in sql
    assert result["cutoff"] == (NOW - timedelta(days=180)).isoformat()
    assert release.calls == [], "a lead row is not a bucket object"


# ================================================ 5. the sweep visits them in order ==


class _Policy:
    def __init__(self, data_class: str, days: int | None, status: str = "active") -> None:
        self.data_class = data_class
        self.retention_days = days
        self.status = status
        self.last_run_at = None


class _SweepSession:
    """Enumeration in whatever order the database returned it, plus the gate."""

    def __init__(self, policies: list[_Policy]) -> None:
        self.policies = policies
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        parsed = dict(params or {})
        self.statements.append(sql)
        if "FROM tenants" in sql:
            return _Result(((True,),))
        if "INSERT INTO audit_logs" in sql:
            return _Result()
        if "retention_policies" in sql and "data_class" in parsed:
            match = next(
                (p for p in self.policies if p.data_class == parsed["data_class"]), None
            )
            return _Result(((match.retention_days, match.status),) if match else ())
        if "retention_policies" in sql:
            return _Result(tuple(self.policies))
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            return _Result(())
        if sql.strip().upper().startswith("DELETE"):
            return _Result(rowcount=1)
        raise AssertionError(f"unexpected statement: {sql[:140]}")


async def test_the_sweep_reaches_every_new_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import retention_worker

    seen: list[str] = []

    async def fake_purge(session, tenant_id, data_class, *, now=None):
        seen.append(data_class)
        return {"data_class": data_class, "deleted": 1, "skipped_reason": None}

    monkeypatch.setattr(retention_worker, "purge_row_store", fake_purge)
    session = _SweepSession([_Policy(MESSAGES, 365), _Policy(LEADS, 180), _Policy(ATTACHMENTS, 90)])
    summary = await retention_worker.RetentionWorker.run_once(session, TENANT)

    assert set(seen) == {MESSAGES, ATTACHMENTS, LEADS}
    assert summary["skipped"] == []
    assert summary["policies"] == 3


async def test_the_sweep_clears_media_before_it_clears_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tenant chose both horizons; if the sweep visits ``messages`` first it
    cascades attachment rows away with no keys in hand — the leak this file
    exists for. The order must come from the dependency, not from the database."""
    from app.workers import retention_worker

    seen: list[str] = []

    async def fake_purge(session, tenant_id, data_class, *, now=None):
        seen.append(data_class)
        return {"data_class": data_class, "deleted": 1, "skipped_reason": None}

    monkeypatch.setattr(retention_worker, "purge_row_store", fake_purge)
    # Deliberately reversed: the enumeration must not decide the order.
    session = _SweepSession([_Policy(MESSAGES, 365), _Policy(ATTACHMENTS, 90)])
    await retention_worker.RetentionWorker.run_once(session, TENANT)
    assert seen.index(ATTACHMENTS) < seen.index(MESSAGES), seen


def test_the_declaration_order_matches_the_dependency_order() -> None:
    """The allowlist is read in order by the sweep, so a child must be declared
    before the parent that cascades it."""
    order = list(retention.ROW_LEVEL_DATA_CLASSES)
    assert order.index(ATTACHMENTS) < order.index(MESSAGES), order


# ============================================ 6. the object side of the purge ==


def _storage(client=None, *, bucket="b") -> Any:
    from app.core.storage import ObjectStorage

    storage = ObjectStorage.__new__(ObjectStorage)
    storage._bucket = bucket
    storage._endpoint = "https://s3.test" if client is not None else None
    storage._region = "us-east-1"
    storage._key = "k" if client is not None else ""
    storage._secret = "s" if client is not None else ""
    storage._client = client
    # The supabase half of __init__ (rest client + url/key + url cache): the
    # configured() predicate reads BOTH halves, so an object built via
    # __new__ must carry the whole attribute surface or the delete path
    # dies on a missing attribute instead of answering "nothing configured".
    storage._supabase_url = ""
    storage._supabase_key = ""
    storage._rest_client = None
    storage._signed_url_cache = {}
    return storage


async def test_the_bucket_delete_reports_the_keys_it_could_not_remove() -> None:
    """``release_media_objects`` is only useful if a per-key failure survives it:
    a silently leaked object is exactly the hole this file closes."""
    calls: list[Any] = []

    class _Client:
        def delete_objects(self, **kwargs):
            calls.append(kwargs)
            return {"Errors": [{"Key": "media/b.jpg", "Code": "AccessDenied"}]}

    failed = await _storage(_Client()).delete_objects(["media/a.jpg", "media/b.jpg"])

    assert failed == ["media/b.jpg"]
    assert calls and calls[0]["Bucket"] == "b"
    assert [o["Key"] for o in calls[0]["Delete"]["Objects"]] == ["media/a.jpg", "media/b.jpg"]


async def test_no_bucket_configured_means_nothing_to_release() -> None:
    """When S3 is not configured ``store`` kept the expiring provider URL and
    wrote no object, so a release has nothing to remove — it must not raise."""
    assert await _storage(bucket="").delete_objects(["media/a.jpg"]) == []


async def test_an_unreachable_bucket_fails_the_release_not_the_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rows are already gone; a bucket that refuses must be reported as a
    leak, not turn the sweep into a 500 that rolls the purge back."""

    def _boom(keys):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr(retention, "get_storage", lambda: _SimpleNamespace(_boom))
    audit = _AuditRecorder()
    monkeypatch.setattr(retention, "write_audit_row", audit)
    session = _MediaSession(
        policy=(365, "active"),
        media_rows=((uuid.uuid4(), "media/a.jpg"),),
        rowcounts=[1],
    )
    result = await retention.purge_row_store(session, TENANT, ATTACHMENTS, now=NOW)
    assert result["deleted"] == 1
    assert result["media_objects_failed"] == ["media/a.jpg"]
    assert audit.kwargs[0]["after"]["media_objects_failed"] == ["media/a.jpg"]


class _SimpleNamespace:
    def __init__(self, delete_objects) -> None:
        self._delete_objects = delete_objects

    async def delete_objects(self, keys):
        return self._delete_objects(list(keys))
