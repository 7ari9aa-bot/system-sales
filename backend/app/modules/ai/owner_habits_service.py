"""Habit suggestions for ONE owner: measure, offer, accept, dismiss.

The only input is the owner's own questions, taken from the threads THEY started in THIS shop.
A colleague's questions, another shop's, and the assistant's own answers never count. Accepting
takes a period KEY, not text: the habit is measured again here and the module's fixed sentence is
what gets saved, so a request cannot carry words into the memory.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIChatMessage, AIChatThread, OwnerMemory, OwnerMemorySettings
from app.modules.ai.owner_habits import (
    PERIODS,
    RECENT_QUESTIONS,
    Habit,
    detect_period_habit,
    suggestion_text,
)
from app.modules.ai.owner_memory import MemoryRefused, OwnerMemoryService, _key


class HabitNotFound(Exception):  # noqa: N818 - an absent habit is a normal outcome, not an error
    """The period is not (or no longer) a habit of this owner."""


class OwnerHabitService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._memory = OwnerMemoryService(session, tenant_id, user_id)

    async def _recent_questions(self) -> list[str]:
        rows = await self.session.execute(
            sa.select(AIChatMessage.content)
            .join(AIChatThread, AIChatThread.id == AIChatMessage.thread_id)
            .where(
                AIChatMessage.tenant_id == self.tenant_id,
                AIChatThread.tenant_id == self.tenant_id,
                AIChatThread.created_by_user_id == self.user_id,
                AIChatMessage.role == "user",
            )
            # Newest first by the THREAD's time and then the turn number inside it. The message's
            # own created_at is now(), frozen per transaction, so turns written together share an
            # instant and ordering by it (or by their random ids) is arbitrary.
            .order_by(
                AIChatThread.created_at.desc(),
                AIChatThread.id.desc(),
                AIChatMessage.sequence_no.desc(),
            )
            .limit(RECENT_QUESTIONS)
        )
        return [r[0] for r in rows]

    async def _dismissed(self) -> set[str]:
        row = (
            await self.session.execute(
                sa.select(OwnerMemorySettings.dismissed_habits).where(
                    OwnerMemorySettings.tenant_id == self.tenant_id,
                    OwnerMemorySettings.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        return {p for p in (row or []) if p in PERIODS}

    async def _already_remembered(self, habit: Habit) -> bool:
        key = _key(habit.suggestion)
        found = (
            await self.session.execute(
                sa.select(OwnerMemory.id).where(
                    OwnerMemory.tenant_id == self.tenant_id,
                    OwnerMemory.user_id == self.user_id,
                    OwnerMemory.content_key == key,
                )
            )
        ).first()
        return found is not None

    async def _current(self) -> Habit | None:
        if not await self._memory.is_enabled():
            return None
        habit = detect_period_habit(await self._recent_questions())
        if habit is None or habit.period in await self._dismissed():
            return None
        if await self._already_remembered(habit):
            return None
        return habit

    async def suggestions(self) -> list[Habit]:
        habit = await self._current()
        return [habit] if habit is not None else []

    async def accept(self, period: str) -> OwnerMemory:
        """Save the fixed sentence for ``period`` if, and only if, it is this owner's habit now."""
        # Off is a state the owner can fix, not a missing suggestion: say so (409), not "not found".
        if not await self._memory.is_enabled():
            raise MemoryRefused("disabled")
        habit = await self._current()
        if habit is None or habit.period != period or suggestion_text(period) is None:
            raise HabitNotFound(period)
        return await self._memory.remember(habit.suggestion, source="inferred")

    async def dismiss(self, period: str) -> None:
        if suggestion_text(period) is None:
            raise HabitNotFound(period)
        settings = (
            await self.session.execute(
                sa.select(OwnerMemorySettings).where(
                    OwnerMemorySettings.tenant_id == self.tenant_id,
                    OwnerMemorySettings.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        if settings is None:
            self.session.add(
                OwnerMemorySettings(
                    tenant_id=self.tenant_id, user_id=self.user_id, dismissed_habits=[period]
                )
            )
        elif period not in settings.dismissed_habits:
            settings.dismissed_habits = [*settings.dismissed_habits, period]
        await self.session.flush()


__all__ = ["HabitNotFound", "MemoryRefused", "OwnerHabitService"]
