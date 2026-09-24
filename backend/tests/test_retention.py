"""DB-free unit tests for the retention worker (spec §52).

These cover the pure decision logic that makes retention safe:

- a RetentionPolicy naming a data_class outside the ``analytics.retention``
  allowlist is SKIPPED and reported, never guessed at;
- a horizon the gate refuses — absent, paused, or non-positive — is REFUSED by
  the module the worker delegates to, and reported under the module's own reason
  (the worker has no vocabulary of its own);
- the ``_RETENTABLE`` allowlist is DERIVED from that module and contains no store
  the PII map (docs/PII_DATA_MAP.md, §131) marks as legally retained — the guard
  rail, in one place.

No database is touched: the session is a tiny async double.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.analytics import retention
from app.workers.retention_worker import _RETENTABLE, RetentionWorker

TENANT_ID = "11111111-1111-1111-1111-111111111111"

# Stores the PII map says must be kept for legal reasons (financial / audit).
# Retention must NEVER hard-delete from any of these.
LEGALLY_RETAINED = {
    "orders",
    "payments",
    "audit_logs",
    "customers",
    "customer_identities",
}


class _Result:
    """Stand-in for a SQLAlchemy CursorResult."""

    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        """First column of the first row — or the row itself when the double was
        built with a bare value (``_Result([True])`` for a one-column probe)."""
        if not self._rows:
            return None
        first = self._rows[0]
        return first[0] if isinstance(first, tuple) else first


class _Session:
    """Async session double, routing by SQL shape like the real statements do.

    One enumeration (the policy ``SELECT``), then whatever the gated executor
    asks: the tenant-liveness probe, its own re-read of the policy row, the
    bounded ``DELETE``s, and the §66 audit append.
    """

    def __init__(self, policies, delete_rowcounts=None):
        self._policies = list(policies)
        self._delete_rowcounts = list(delete_rowcounts or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.audits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params or {})
        if "FROM tenants" in sql:
            return _Result([True])
        if "INSERT INTO audit_logs" in sql:
            self.audits += 1
            return _Result()
        if "retention_policies" in sql and "data_class" in (params or {}):
            wanted = params["data_class"]
            match = next((p for p in self._policies if p.data_class == wanted), None)
            return _Result(
                [(match.retention_days, match.status)] if match else []
            )
        if "retention_policies" in sql:
            return _Result(self._policies)
        if sql.strip().upper().startswith("SELECT") and "storage_key" in sql:
            # §52 media gather: this double holds no attachment rows, so a batch
            # never carries media. The media path itself is pinned in
            # tests/test_media_and_lead_retention.py.
            return _Result([])
        if sql.strip().upper().startswith("DELETE"):
            rowcount = self._delete_rowcounts.pop(0) if self._delete_rowcounts else 0
            return _Result(rowcount=rowcount)
        raise AssertionError(f"unexpected statement: {sql[:140]}")


def _policy(data_class, days, status="active"):
    return SimpleNamespace(
        data_class=data_class,
        retention_days=days,
        status=status,
        last_run_at=None,
    )


async def test_unknown_data_class_is_skipped_not_guessed():
    """A policy naming a table outside the allowlist is skipped and reported."""
    session = _Session([_policy("orders", 30)])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 0
    assert summary["deleted"] == {}
    assert summary["skipped"] == [
        {"data_class": "orders", "reason": retention.REASON_NOT_A_ROW_STORE}
    ]
    # Only the policy SELECT ran: no DELETE was issued and the unknown class
    # never reached a statement.
    assert len(session.statements) == 1
    assert all("DELETE" not in sql for sql in session.statements)
    assert not any("orders" in sql for sql in session.statements)


async def test_non_positive_retention_days_is_refused():
    """0 or negative days would mean "delete everything" — refuse it.

    The refusal is the gate's, so the worker reports the gate's reason verbatim
    instead of inventing a second word for the same block.
    """
    session = _Session([_policy("messages", 0), _policy("ai_usage", -5)])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 0
    assert summary["deleted"] == {}
    assert summary["skipped"] == [
        {"data_class": "messages", "reason": retention.BLOCKED_NO_POSITIVE_HORIZON},
        {"data_class": "ai_usage", "reason": retention.BLOCKED_NO_POSITIVE_HORIZON},
    ]
    assert all("DELETE" not in sql for sql in session.statements)
    assert session.audits == 0


async def test_a_paused_policy_is_reported_not_silently_dropped():
    """The sweep enumerates EVERY policy row, so "nobody consented" is visible in
    the summary instead of being an empty result nobody can distinguish from a
    tenant that has no policy at all."""
    session = _Session([_policy("messages", 365, status="paused")])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 0
    assert summary["skipped"] == [
        {"data_class": "messages", "reason": retention.BLOCKED_NO_CHOSEN_POLICY}
    ]
    assert all("DELETE" not in sql for sql in session.statements)


def test_retentable_map_excludes_legally_retained_stores():
    """GUARD RAIL: the allowlist must not name any legally retained store."""
    tables = {table for table, _column in _RETENTABLE.values()}
    assert tables.isdisjoint(LEGALLY_RETAINED)
    # The stores a tenant can hold a horizon for. ``attachments`` and ``leads``
    # joined it with §52's own data-class list (media has a policy, a marketing
    # lead is someone's phone number) — tests/test_media_and_lead_retention.py
    # pins why each is there, and REFUSED_DATA_CLASSES pins what stays out.
    assert set(_RETENTABLE) == {
        "attachments",
        "messages",
        "ai_usage",
        "webhook_events",
        "leads",
    }
    assert tables == set(_RETENTABLE)
    assert set(retention.REFUSED_DATA_CLASSES).isdisjoint(_RETENTABLE)


def test_retentable_map_is_the_modules_allowlist_not_a_copy():
    """Two lists of "which tables may be destroyed" is how the wrong one drifts."""
    assert _RETENTABLE is not retention.ROW_LEVEL_DATA_CLASSES
    assert dict(_RETENTABLE) == {
        dc: (spec.table, spec.ts_column)
        for dc, spec in retention.ROW_LEVEL_DATA_CLASSES.items()
    }


def test_retentable_columns_match_model_timestamps():
    """Each mapping resolves to the model's real age column."""
    assert _RETENTABLE["messages"] == ("messages", "created_at")
    assert _RETENTABLE["ai_usage"] == ("ai_usage", "created_at")
    assert _RETENTABLE["webhook_events"] == ("webhook_events", "received_at")
    assert _RETENTABLE["attachments"] == ("attachments", "created_at")
    assert _RETENTABLE["leads"] == ("leads", "created_at")


async def test_allowed_policy_deletes_in_bounded_batches_and_stamps_last_run():
    policy = _policy("messages", 30)
    # Two full batches then a short one → three statements, 1012 rows total.
    session = _Session([policy], delete_rowcounts=[500, 500, 12])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 1
    assert summary["deleted"] == {"messages": 1012}
    assert summary["skipped"] == []
    assert policy.last_run_at is not None

    deletes = [sql for sql in session.statements if "DELETE" in sql]
    assert len(deletes) == 3
    assert all("LIMIT" in sql for sql in deletes)  # bounded, never unbounded
    assert all("tenant_id" in sql for sql in deletes)
    assert session.audits == 1, "a sweep that deleted 1012 rows silently is the §66 hole"
