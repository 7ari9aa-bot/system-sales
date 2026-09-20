"""Spec §43/§44 governance and the §39 ANN index migration — DB-free tests.

Two properties are pinned here without a database, because both are invisible
to the DB-backed suite:

1. §43 data-egress precedence in :func:`app.modules.ai.policy.decide` — the
   fail-open default, and that an explicit deny beats any allow. ``decide`` is a
   pure function over an in-memory ``AIProviderPolicy``, so no session is needed.
2. The §39 migration declares exactly ONE ANN index per embedding table. The
   index is the entire point of the revision; a future edit that silently drops
   one table's index would otherwise only show up as a slow query in production.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from app.modules.ai.models import AIProviderPolicy
from app.modules.ai.policy import decide

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
ANN_MIGRATION = VERSIONS_DIR / "b8c9d0e1f2a3_ai_embedding_ann_indexes.py"


def _policy(**overrides) -> AIProviderPolicy:
    """An in-memory policy row — never flushed, so no DB is required."""
    fields: dict = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "provider": "openai",
        "status": "allowed",
        "allowed_models": [],
        "pii_redaction_required": False,
        "data_classification": "internal",
    }
    fields.update(overrides)
    return AIProviderPolicy(**fields)


# ------------------------------------------------------ §43 policy precedence --


def test_absent_policy_is_allowed_fail_open() -> None:
    """No policy row ⇒ allowed, with no policy id to attribute the decision to.

    Fail-open is the house default for capabilities (see ``EntitlementService``):
    shipping enforcement must not silently cut off every tenant that has not
    been given a policy yet.
    """
    decision = decide(None, provider="openai", model="gpt-4", data_class="restricted")
    assert decision.allowed is True
    assert decision.redact_required is False
    assert decision.policy_id is None
    assert "fail-open" in decision.reason


def test_explicit_deny_beats_allowed_model() -> None:
    """A deny wins even when the model appears in the allow-list."""
    policy = _policy(status="denied", allowed_models=["gpt-4"])
    decision = decide(policy, provider="openai", model="gpt-4", data_class="public")
    assert decision.allowed is False
    assert decision.policy_id == policy.id
    assert "denied" in decision.reason


def test_allow_policy_permits_listed_model() -> None:
    policy = _policy(status="allowed", allowed_models=["gpt-4", "gpt-4o"])
    decision = decide(policy, provider="openai", model="gpt-4o", data_class="internal")
    assert decision.allowed is True
    assert decision.policy_id == policy.id


def test_allow_policy_denies_unlisted_model() -> None:
    policy = _policy(status="allowed", allowed_models=["gpt-4"])
    decision = decide(policy, provider="openai", model="gpt-3.5", data_class="internal")
    assert decision.allowed is False
    assert "allowed_models" in decision.reason


def test_empty_allow_list_permits_any_model() -> None:
    """An empty allow-list means "any model", not "no model"."""
    policy = _policy(status="allowed", allowed_models=[])
    decision = decide(policy, provider="openai", model="anything", data_class="internal")
    assert decision.allowed is True


def test_redaction_requirement_is_surfaced() -> None:
    policy = _policy(pii_redaction_required=True)
    decision = decide(policy, provider="openai", model="gpt-4", data_class="internal")
    assert decision.allowed is True
    assert decision.redact_required is True


def test_classification_above_clearance_is_denied() -> None:
    policy = _policy(data_classification="internal")
    decision = decide(policy, provider="openai", model="gpt-4", data_class="confidential")
    assert decision.allowed is False
    assert "exceeds" in decision.reason


@pytest.mark.parametrize("data_class", ["public", "internal"])
def test_classification_at_or_below_clearance_is_allowed(data_class: str) -> None:
    policy = _policy(data_classification="internal")
    decision = decide(policy, provider="openai", model="gpt-4", data_class=data_class)
    assert decision.allowed is True


def test_unknown_classification_is_unranked() -> None:
    """A token off the ladder cannot be compared, so the check is skipped.

    Guessing an ordering would be worse than not enforcing one; an operator who
    wants strictness uses a ranked value.
    """
    policy = _policy(data_classification="internal")
    decision = decide(policy, provider="openai", model="gpt-4", data_class="pii")
    assert decision.allowed is True


# ------------------------------------------------- §39 ANN index migration --


class _RecordingOp:
    """Minimal Alembic ``op`` stand-in that records ``execute()`` SQL."""

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def execute(self, sql, *args, **kwargs) -> None:
        if isinstance(sql, str):
            self._captured.append(sql)

    def __getattr__(self, name: str):
        return lambda *a, **k: None


def _load_migration():
    captured: list[str] = []
    spec = importlib.util.spec_from_file_location("ann_migration_under_test", ANN_MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.op = _RecordingOp(captured)
    return module, captured


def test_migration_declares_exactly_one_index_per_table() -> None:
    """Both embedding tables get exactly one HNSW cosine index — no more, no less."""
    module, captured = _load_migration()
    module.upgrade()

    assert len(captured) == 2, f"expected 2 statements, got {len(captured)}"
    per_table: dict[str, int] = {}
    for sql in captured:
        assert "USING hnsw" in sql
        assert "vector_cosine_ops" in sql  # matches cosine_distance() in knowledge.py
        assert "IF NOT EXISTS" in sql
        for table in ("knowledge_items", "memories"):
            if f"ON {table} " in sql:
                per_table[table] = per_table.get(table, 0) + 1

    assert per_table == {"knowledge_items": 1, "memories": 1}


def test_migration_revision_chain() -> None:
    """The revision id and its parent are the contract with the other engineer."""
    module, _ = _load_migration()
    assert module.revision == "b8c9d0e1f2a3"
    assert module.down_revision == "a7b8c9d0e1f2"


def test_migration_downgrade_drops_both_indexes() -> None:
    """downgrade() must drop exactly the two indexes upgrade() creates."""
    module, captured = _load_migration()
    module.upgrade()
    module.downgrade()

    created_names = {
        sql.split(" IF NOT EXISTS ", 1)[1].split(" ON ", 1)[0]
        for sql in captured
        if sql.startswith("CREATE INDEX")
    }
    dropped_names = {
        sql.replace("DROP INDEX IF EXISTS ", "")
        for sql in captured
        if sql.startswith("DROP INDEX IF EXISTS")
    }
    assert len(created_names) == 2
    assert created_names == dropped_names
