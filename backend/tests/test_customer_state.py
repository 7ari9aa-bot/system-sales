"""State engine tests (spec §8/§20) — real conversation_agent_states rows.

The engine owns the truth the no-resend rule and the referent resolver read;
these pin the closed patch vocabulary, the append-dedupe semantics, the
no-op-does-not-bump rule, and optimistic concurrency (stale version fails
instead of silently overwriting).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import DomainError
from app.modules.ai.agents.customer.state import (
    StaleStateError,
    apply_patch,
    load_state,
)
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer


async def _seed_conversation(db, tenant_id) -> uuid.UUID:
    customer = Customer(tenant_id=tenant_id, name="State Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    return conversation.id


async def test_first_patch_creates_row_at_version_one(db, tenant_ctx):
    conversation_id = await _seed_conversation(db, tenant_ctx.tenant_id)
    assert await load_state(db, tenant_ctx.tenant_id, conversation_id) is None

    state = await apply_patch(
        db,
        tenant_ctx.tenant_id,
        conversation_id,
        {"shown_items": ["p-1", "p-2"], "sent_media": ["img-1"]},
    )
    assert state.state_version == 1
    assert state.shown_items == ["p-1", "p-2"]
    assert state.sent_media == ["img-1"]


async def test_second_patch_appends_deduplicates_and_bumps(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation_id = await _seed_conversation(db, tenant_id)
    await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-1"]})

    state = await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-1", "p-2"]})
    # p-1 already there: only p-2 grew the state, order preserved.
    assert state.shown_items == ["p-1", "p-2"]
    assert state.state_version == 2


async def test_noop_patch_leaves_version_alone(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation_id = await _seed_conversation(db, tenant_id)
    await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-1"]})

    state = await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-1"]})
    assert state.state_version == 1, "a no-op is not a state change"


async def test_lists_never_shrink_through_a_patch(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation_id = await _seed_conversation(db, tenant_id)
    await apply_patch(db, tenant_id, conversation_id, {"sent_media": ["img-1", "img-2"]})

    state = await apply_patch(db, tenant_id, conversation_id, {"sent_media": ["img-1"]})
    assert state.sent_media == ["img-1", "img-2"]


async def test_unknown_patch_keys_fail_loudly(db, tenant_ctx):
    conversation_id = await _seed_conversation(db, tenant_ctx.tenant_id)
    with pytest.raises(DomainError, match="unknown state patch keys"):
        await apply_patch(db, tenant_ctx.tenant_id, conversation_id, {"mood": "angry"})


async def test_non_string_values_fail(db, tenant_ctx):
    conversation_id = await _seed_conversation(db, tenant_ctx.tenant_id)
    with pytest.raises(DomainError, match="list of strings"):
        await apply_patch(db, tenant_ctx.tenant_id, conversation_id, {"shown_items": [1, 2]})


async def test_stale_expected_version_fails_instead_of_overwriting(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation_id = await _seed_conversation(db, tenant_id)
    await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-1"]})
    # A concurrent writer moves the state forward AFTER our caller read it.
    await apply_patch(db, tenant_id, conversation_id, {"shown_items": ["p-0"]})

    # Our caller read version 1; the row is now at 2.
    with pytest.raises(StaleStateError, match="state_version moved"):
        await apply_patch(
            db,
            tenant_id,
            conversation_id,
            {"shown_items": ["p-2"]},
            expected_version=1,
        )


async def test_expected_version_on_missing_row_only_allows_zero(db, tenant_ctx):
    conversation_id = await _seed_conversation(db, tenant_ctx.tenant_id)
    with pytest.raises(StaleStateError):
        await apply_patch(
            db,
            tenant_ctx.tenant_id,
            conversation_id,
            {"shown_items": ["p-1"]},
            expected_version=3,
        )
