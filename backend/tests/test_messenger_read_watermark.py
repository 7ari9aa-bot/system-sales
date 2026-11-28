"""A Messenger read receipt is a time, so the ingest step must apply it by time.

``messaging[].read`` carries only ``watermark`` (everything we sent before it was read) and no
message id, so the id-based status path can never apply it. `apply_read_watermarks` does, and only
to this customer's sent/delivered outbound rows up to that moment.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from app.applications.apparel.modules.conversations.gateway import ingest as ingest_module
from app.applications.apparel.modules.conversations.gateway.ingest import IngestService


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    """Records every statement so the test can read what would have been written."""

    def __init__(self, conversation_ids):
        self.conversation_ids = conversation_ids
        self.statements: list = []

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if "customer_identities" in str(statement):
            return _Result(self.conversation_ids)
        return _Result([])


@pytest.mark.asyncio
async def test_a_read_watermark_marks_that_customers_sent_messages_read() -> None:
    conversation = uuid.uuid4()
    session = _Session([conversation])
    tenant = uuid.uuid4()
    await IngestService.apply_read_watermarks(
        session, tenant, "messenger", [{"customer_ref": "PSID-1", "watermark": 1700000000900}]
    )
    lookup, params = session.statements[0]
    assert params == {"tenant": tenant, "channel": "messenger", "ref": "PSID-1"}
    update = str(session.statements[1][0])
    assert "UPDATE messages" in update
    compiled = session.statements[1][0].compile()
    assert "read" in compiled.params.values()
    # only rows that already left can become read; never a queued/failed one
    assert ("sent", "delivered") in compiled.params.values() or {"sent", "delivered"} <= {
        v for p in compiled.params.values() if isinstance(p, (list, tuple)) for v in p
    }
    assert datetime.fromtimestamp(1700000000.9, tz=UTC) in compiled.params.values()


@pytest.mark.asyncio
async def test_an_unknown_customer_writes_nothing() -> None:
    session = _Session([])
    await IngestService.apply_read_watermarks(
        session, uuid.uuid4(), "messenger", [{"customer_ref": "ghost", "watermark": 1}]
    )
    assert len(session.statements) == 1  # the lookup only, no UPDATE


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", "not-a-number"])
async def test_a_malformed_watermark_is_ignored(bad) -> None:
    session = _Session([uuid.uuid4()])
    await IngestService.apply_read_watermarks(
        session, uuid.uuid4(), "messenger", [{"customer_ref": "PSID-1", "watermark": bad}]
    )
    assert session.statements == []


def test_the_webhook_processing_block_applies_read_watermarks() -> None:
    """The hook exists only if process_webhook_event actually calls it."""
    source = inspect.getsource(ingest_module.IngestService.process_webhook_event)
    assert "parse_read_watermarks" in source
    assert "apply_read_watermarks" in source
