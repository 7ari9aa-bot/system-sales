"""The durable side of a session: the tables, the guard on them, and the row mapping.

These are static checks on purpose. The runtime behaviour (a session surviving a worker restart)
needs PostgreSQL, and CI proves it there; what must never regress silently is that a voice table
exists with `tenant_id`, is FORCE RLS guarded by exactly the canonical policy, and that
`provision.py` therefore picks it up (it derives its guard list from `Base.metadata`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

# The voice tables now carry real foreign keys into the conversation tables, so resolving
# `sorted_tables` needs those tables registered too. Importing the registry is also what
# provision.py itself does — this is the faithful set of tables, not a convenience import.
import app.core.model_registry  # noqa: E402,F401
from app.core.db import Base
from app.modules.voice.domain.models import VoiceSessionRow, VoiceTurnRow
from app.modules.voice.domain.personas import PersonaType, PrincipalType
from app.modules.voice.domain.states import VoiceSessionState
from app.modules.voice.infrastructure.sql_store import _to_record
from app.modules.voice.security.capabilities import AuthenticationLevel, ChannelType

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "fe2026112701_voice_sessions_and_turns.py"
)


def test_both_voice_tables_carry_the_tenant_column() -> None:
    for table in (VoiceSessionRow.__table__, VoiceTurnRow.__table__):
        assert "tenant_id" in table.columns, f"{table.name} lost its tenant column"


def test_metadata_exposes_the_voice_tables_so_provision_guards_them() -> None:
    # provision.py derives the tables it locks down from Base.metadata; a table that is only
    # created by a migration and never imported would be provisioned without RLS.
    names = {t.name for t in Base.metadata.sorted_tables}
    assert {"voice_sessions", "voice_turns"} <= names


def test_the_migration_forces_rls_with_exactly_the_canonical_policy() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    # The migration loops over _TABLES, so the guard is proven by the template plus the table
    # list rather than by four literal statements per table.
    for table in ("voice_sessions", "voice_turns"):
        assert table in source
        assert "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in source
        assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in source
        assert "CREATE POLICY tenant_isolation ON {table} " in source
        assert "GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_app" in source
        assert '_TABLES = ("voice_sessions", "voice_turns")' in source
    # The guard must be the app's tenant GUC, not a permissive `USING (true)`.
    assert "NULLIF(current_setting('app.tenant_id', true), '')::uuid" in source
    assert "USING (true)" not in source


def test_a_retried_client_key_is_unique_per_tenant() -> None:
    index = next(
        i for i in VoiceSessionRow.__table__.indexes if i.name == "ux_voice_sessions_client_key"
    )
    assert index.unique is True
    assert [c.name for c in index.columns] == ["tenant_id", "client_key"]


def test_a_row_maps_back_to_the_session_the_worker_started() -> None:
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    started = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)
    row = VoiceSessionRow(
        id=session_id,
        tenant_id=tenant_id,
        workspace_id=None,
        principal_type="merchant_user",
        principal_id=uuid.uuid4(),
        persona="merchant_assistant",
        channel="web_voice",
        state="ACTIVE",
        authentication_level=2,
        scopes=["orders:read", "inventory:read"],
        agent_version_id=None,
        policy_version="v1",
        provider_session_id="prov-1",
        provider_name="fake-live",
        trace_id="trace-1",
        client_key=None,
        last_completed_turn=3,
        close_reason=None,
        expires_at=None,
        started_at=started,
        updated_at=started,
    )

    record = _to_record(row)

    assert record.session_id == session_id
    assert record.tenant_id == tenant_id
    assert record.capability.persona is PersonaType.MERCHANT_ASSISTANT
    assert record.capability.principal_type is PrincipalType.MERCHANT_USER
    assert record.capability.authentication_level is AuthenticationLevel.VERIFIED
    assert record.capability.channel is ChannelType.WEB_VOICE
    assert record.state is VoiceSessionState.ACTIVE
    assert record.capability.scopes == frozenset({"orders:read", "inventory:read"})
    assert record.last_completed_turn == 3
    assert record.provider_session_id == "prov-1"
