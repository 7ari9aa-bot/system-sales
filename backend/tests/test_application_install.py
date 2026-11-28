"""Finishing setup installs what was paid for, and only that.

No database: the point of these tests is the decision, so the session is a stub
that records what would be written and answers the "what already exists" query.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.modules.applications import install as install_module


class _Rows:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def scalars(self):
        return self

    def all(self):
        return self._keys


class _Session:
    """A session that records adds instead of writing them."""

    def __init__(self, existing: list[str] | None = None) -> None:
        self.existing = existing or []
        self.added: list[object] = []
        self.flushed = 0

    async def execute(self, _statement):
        return _Rows(self.existing)

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1


@pytest.fixture()
def entitled_keys(monkeypatch):
    """Let each test say what the subscription covers."""

    def _set(keys: set[str]) -> None:
        async def _fake(session, *, tenant_id, workspace_id):  # noqa: ANN001
            return frozenset(keys)

        monkeypatch.setattr(install_module, "entitled", _fake)

    return _set


def test_installs_only_what_is_entitled(entitled_keys) -> None:
    entitled_keys({"retail.core", "retail.purchasing"})
    session = _Session()
    installed = asyncio.run(
        install_module.install_entitled(
            session, tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4()
        )
    )
    assert installed == ["retail.core", "retail.purchasing"]
    assert [row.application_key for row in session.added] == installed
    assert all(row.state == "active" and row.is_active for row in session.added)
    assert session.flushed == 1


def test_nothing_entitled_writes_nothing(entitled_keys) -> None:
    entitled_keys(set())
    session = _Session()
    installed = asyncio.run(
        install_module.install_entitled(
            session, tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4()
        )
    )
    assert installed == []
    assert session.added == []
    assert session.flushed == 0


def test_an_existing_installation_is_never_reopened(entitled_keys) -> None:
    """A product somebody switched off stays off, even if it is still paid for."""
    entitled_keys({"retail.core"})
    session = _Session(existing=["retail.core"])
    installed = asyncio.run(
        install_module.install_entitled(
            session, tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4()
        )
    )
    assert installed == []
    assert session.added == []


def test_only_the_missing_ones_are_installed(entitled_keys) -> None:
    entitled_keys({"retail.core", "retail.purchasing"})
    session = _Session(existing=["retail.core"])
    installed = asyncio.run(
        install_module.install_entitled(
            session, tenant_id=uuid.uuid4(), workspace_id=uuid.uuid4()
        )
    )
    assert installed == ["retail.purchasing"]


def test_the_setup_hook_does_nothing_without_a_workspace(entitled_keys) -> None:
    entitled_keys({"retail.core"})
    session = _Session()

    class _Ctx:
        tenant_id = uuid.uuid4()
        workspace_id = None

    result: dict = {}
    asyncio.run(install_module._install_after_setup(_Ctx(), result))
    assert result == {}
    assert session.added == []
