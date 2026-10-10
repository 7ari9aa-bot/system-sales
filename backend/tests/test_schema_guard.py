"""Schema-skew guard (P0-4): the decision matrix and the boot refusal."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.core.schema_guard import (
    SchemaSkewError,
    assert_schema_current,
    classify_schema_state,
    code_head,
)

HEAD = "fe2026100810"


class TestClassify:
    def test_aligned_is_none(self) -> None:
        assert classify_schema_state([HEAD], HEAD) is None

    def test_uninitialized_schema(self) -> None:
        reason = classify_schema_state([], HEAD)
        assert reason is not None and "not initialized" in reason

    def test_forked_version_table(self) -> None:
        reason = classify_schema_state(["aaa", "bbb"], HEAD)
        assert reason is not None and "forked" in reason

    def test_database_behind_code(self) -> None:
        reason = classify_schema_state(["fe2026100802"], HEAD)
        assert reason is not None
        assert "fe2026100802" in reason and HEAD in reason
        assert "skewed" in reason

    def test_database_ahead_of_code_is_also_skew(self) -> None:
        reason = classify_schema_state(["zzz_newer"], HEAD)
        assert reason is not None and "skewed" in reason

    def test_missing_revisions_directory(self) -> None:
        reason = classify_schema_state([HEAD], None)
        assert reason is not None and "no alembic revisions" in reason


class _FakeConn:
    def __init__(self, applied: list[str] | None) -> None:
        self._applied = applied

    async def execute(self, stmt) -> MagicMock:
        result = MagicMock()
        if "to_regclass" in str(stmt):
            result.scalar_one.return_value = (
                "alembic_version" if self._applied is not None else None
            )
        else:
            result.scalars.return_value.all.return_value = self._applied or []
        return result


class _FakeEngine:
    def __init__(self, applied: list[str] | None) -> None:
        self._applied = applied

    def connect(self):
        conn = _FakeConn(self._applied)

        @asynccontextmanager
        async def _ctx():
            yield conn

        return _ctx()


async def test_assert_schema_current_passes_when_aligned() -> None:
    await assert_schema_current(_FakeEngine([code_head()]))


async def test_assert_schema_current_refuses_skewed_database() -> None:
    with pytest.raises(SchemaSkewError, match="fe2026100802"):
        await assert_schema_current(_FakeEngine(["fe2026100802"]))


async def test_assert_schema_current_refuses_uninitialized_database() -> None:
    with pytest.raises(SchemaSkewError, match="not initialized"):
        await assert_schema_current(_FakeEngine(None))


def test_code_head_reads_the_script_directory() -> None:
    # Not pinned to a specific revision — that would turn every new migration
    # into a test edit. What matters: the traversal finds the real chain and
    # resolves exactly one head (a fork would return None here and the boot
    # guard would refuse to start for a different reason).
    head = code_head()
    assert head and len(head) >= 12 and head == head.lower()
