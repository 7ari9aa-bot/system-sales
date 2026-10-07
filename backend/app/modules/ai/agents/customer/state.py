"""Conversation state engine (spec §8/§20) — the state the SYSTEM owns.

The model PROPOSES a state patch; this module DECIDES what a patch may
change and applies it atomically against ``state_version`` (optimistic
concurrency). The patch vocabulary is CLOSED:

* ``{"shown_items": [product_id, ...]}`` — appends, deduplicated, order kept
* ``{"sent_media": [image_id, ...]}``    — appends, deduplicated, order kept

Anything else is rejected loudly (a hallucinated key must not silently
become state), and neither list ever SHRINKS through a patch — forgetting is
a staff operation, not a model whim. The no-resend rule (§13) and the
referent resolver's "التاني" both read from here, so one engine owns the
truth instead of every caller re-implementing the upsert.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.modules.ai.models import ConversationAgentState

_ALLOWED_PATCH_KEYS = frozenset({"shown_items", "sent_media"})


class StaleStateError(DomainError):
    """The patch was cut against an older state_version — re-read and retry."""


def _validate_patch(patch: dict) -> dict[str, list[str]]:
    """Return the normalized patch or raise; unknown keys fail loudly."""
    if not isinstance(patch, dict):
        raise DomainError("state patch must be a dict")
    unknown = set(patch) - _ALLOWED_PATCH_KEYS
    if unknown:
        raise DomainError(f"unknown state patch keys: {sorted(unknown)}")
    normalized: dict[str, list[str]] = {}
    for key, value in patch.items():
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise DomainError(f"state patch {key} must be a list of strings")
        normalized[key] = value
    return normalized


def _append_dedupe(current: list, additions: list[str]) -> tuple[list, bool]:
    """Append without duplicates, preserving order. True when anything grew."""
    merged = list(current or [])
    grew = False
    for item in additions:
        if item not in merged:
            merged.append(item)
            grew = True
    return merged, grew


async def load_state(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationAgentState | None:
    """The conversation's state row, or None when no turn touched it yet."""
    return (
        await session.execute(
            select(ConversationAgentState).where(
                ConversationAgentState.tenant_id == tenant_id,
                ConversationAgentState.conversation_id == conversation_id,
            )
        )
    ).scalar_one_or_none()


async def apply_patch(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    patch: dict,
    *,
    expected_version: int | None = None,
) -> ConversationAgentState:
    """Apply a validated patch and bump ``state_version``.

    Creates the row on first touch (version 1). With ``expected_version``,
    a row whose version moved underneath the caller raises StaleStateError
    instead of silently overwriting — the caller re-reads and re-decides.
    A patch that adds nothing new is a NO-OP: the version does not move,
    because a version bump is a claim that state changed.
    """
    normalized = _validate_patch(patch)
    state = await load_state(session, tenant_id, conversation_id)
    if state is None:
        if expected_version is not None and expected_version != 0:
            raise StaleStateError("state row appeared to exist (version given) but is absent")
        state = ConversationAgentState(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            state={},
            shown_items=[],
            sent_media=[],
            state_version=0,
        )
        session.add(state)

    if expected_version is not None and state.state_version != expected_version:
        raise StaleStateError(
            f"state_version moved: expected {expected_version}, found {state.state_version}"
        )

    grew = False
    for key, additions in normalized.items():
        merged, key_grew = _append_dedupe(getattr(state, key), additions)
        if key_grew:
            setattr(state, key, merged)
            grew = True
    if grew:
        state.state_version += 1
    return state
