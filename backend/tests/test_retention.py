"""DB-free unit tests for the retention worker (spec §52).

These cover the pure decision logic that makes retention safe:

- a RetentionPolicy naming a data_class outside ``_RETENTABLE`` is SKIPPED and
  reported, never guessed at;
- a non-positive ``retention_days`` is refused (0 would mean "delete
  everything", which is unrecoverable);
- the ``_RETENTABLE`` allowlist contains no store the PII map
  (docs/PII_DATA_MAP.md, §131) marks as legally retained — the guard rail.

No database is touched: the session is a tiny async double.
"""

from __future__ import annotations

from types import SimpleNamespace

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


class _Session:
    """Async session double: the first execute returns policies, the rest delete."""

    def __init__(self, policies, delete_rowcounts=None):
        self._policies = list(policies)
        self._delete_rowcounts = list(delete_rowcounts or [])
        self.statements: list[str] = []
        self.params: list[dict] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        if len(self.statements) == 1:
            return _Result(rows=self._policies)
        rowcount = self._delete_rowcounts.pop(0) if self._delete_rowcounts else 0
        return _Result(rowcount=rowcount)


def _policy(data_class, days, status="active"):
    return SimpleNamespace(
        data_class=data_class,
        retention_days=days,
        status=status,
        last_run_at=None,
    )


async def test_unknown_data_class_is_skipped_not_guessed():
    """A policy naming a table outside _RETENTABLE is skipped and reported."""
    session = _Session([_policy("orders", 30)])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 0
    assert summary["deleted"] == {}
    assert summary["skipped"] == [
        {"data_class": "orders", "reason": "unknown_data_class"}
    ]
    # Only the policy SELECT ran: no DELETE was issued and the unknown class
    # never reached a statement.
    assert len(session.statements) == 1
    assert all("DELETE" not in sql for sql in session.statements)
    assert not any("orders" in sql for sql in session.statements)


async def test_non_positive_retention_days_is_refused():
    """0 or negative days would mean "delete everything" — refuse it."""
    session = _Session([_policy("messages", 0), _policy("ai_usage", -5)])
    summary = await RetentionWorker.run_once(session, TENANT_ID)

    assert summary["policies"] == 0
    assert summary["deleted"] == {}
    assert summary["skipped"] == [
        {"data_class": "messages", "reason": "non_positive_retention_days"},
        {"data_class": "ai_usage", "reason": "non_positive_retention_days"},
    ]
    assert len(session.statements) == 1  # no DELETE issued


def test_retentable_map_excludes_legally_retained_stores():
    """GUARD RAIL: the allowlist must not name any legally retained store."""
    tables = {table for table, _column in _RETENTABLE.values()}
    assert tables.isdisjoint(LEGALLY_RETAINED)
    # And it is exactly the documented retention-worker stores.
    assert set(_RETENTABLE) == {"messages", "ai_usage", "webhook_events"}
    assert tables == {"messages", "ai_usage", "webhook_events"}


def test_retentable_columns_match_model_timestamps():
    """Each mapping resolves to the model's real age column."""
    assert _RETENTABLE["messages"] == ("messages", "created_at")
    assert _RETENTABLE["ai_usage"] == ("ai_usage", "created_at")
    assert _RETENTABLE["webhook_events"] == ("webhook_events", "received_at")


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
