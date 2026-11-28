"""Teams and departments: groupings of teammates, never grants.

A team exists to answer "who works together", which the role could not express
without also granting permissions. So nothing in this service touches
``tenant_users.role_id`` or ``role_permissions``: adding someone to a team is a
labelling act, and the permission matrix page is where access is actually decided.

Every method takes the tenant explicitly and filters with it, and the tables are
tenant-scoped under RLS, so a forgotten filter is a refusal rather than a leak.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.platform.identity.models import Team, TeamMember, TenantUser, User


class TeamService:
    @staticmethod
    async def list_teams(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
        """Every team in the workspace with its member count, name-ordered."""
        teams = (
            (
                await session.execute(
                    select(Team).where(Team.tenant_id == tenant_id).order_by(Team.name.asc())
                )
            )
            .scalars()
            .all()
        )
        counts = dict(
            (
                await session.execute(
                    select(TeamMember.team_id, func.count())
                    .where(TeamMember.tenant_id == tenant_id)
                    .group_by(TeamMember.team_id)
                )
            ).all()
        )
        return [
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "member_count": counts.get(team.id, 0),
            }
            for team in teams
        ]

    @staticmethod
    async def create_team(
        session: AsyncSession, tenant_id: uuid.UUID, *, name: str, description: str | None
    ) -> Team:
        name = (name or "").strip()
        if not name:
            raise ValidationError("a team needs a name")
        existing = (
            await session.execute(
                select(Team.id).where(Team.tenant_id == tenant_id, Team.name == name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("a team with that name already exists")
        team = Team(tenant_id=tenant_id, name=name, description=(description or "").strip() or None)
        session.add(team)
        await session.flush()
        return team

    @staticmethod
    async def _get(session: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID) -> Team:
        team = (
            await session.execute(
                select(Team).where(Team.id == team_id, Team.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if team is None:
            # 404, not 403: another tenant's team must not be distinguishable
            # from one that never existed.
            raise NotFoundError("team not found")
        return team

    @staticmethod
    async def rename_team(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        team_id: uuid.UUID,
        *,
        name: str | None,
        description: str | None,
    ) -> Team:
        team = await TeamService._get(session, tenant_id, team_id)
        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationError("a team needs a name")
            clash = (
                await session.execute(
                    select(Team.id).where(
                        Team.tenant_id == tenant_id, Team.name == name, Team.id != team_id
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ConflictError("a team with that name already exists")
            team.name = name
        if description is not None:
            team.description = description.strip() or None
        await session.flush()
        return team

    @staticmethod
    async def delete_team(session: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID) -> None:
        team = await TeamService._get(session, tenant_id, team_id)
        await session.execute(
            delete(TeamMember).where(
                TeamMember.team_id == team.id, TeamMember.tenant_id == tenant_id
            )
        )
        await session.delete(team)
        await session.flush()

    @staticmethod
    async def members(
        session: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID
    ) -> list[dict]:
        await TeamService._get(session, tenant_id, team_id)
        rows = (
            await session.execute(
                select(User.id, User.full_name, User.email)
                .select_from(TeamMember)
                .join(User, User.id == TeamMember.user_id)
                .where(TeamMember.team_id == team_id, TeamMember.tenant_id == tenant_id)
                .order_by(User.full_name.asc())
            )
        ).all()
        return [{"id": row.id, "full_name": row.full_name, "email": row.email} for row in rows]

    @staticmethod
    async def add_member(
        session: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await TeamService._get(session, tenant_id, team_id)
        # The person must belong to this workspace; a team may not pull in a
        # stranger's user id.
        member = (
            await session.execute(
                select(TenantUser.user_id).where(
                    TenantUser.user_id == user_id,
                    TenantUser.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise ValidationError("that person is not a member of this workspace")
        already = (
            await session.execute(
                select(TeamMember.user_id).where(
                    TeamMember.team_id == team_id, TeamMember.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            return
        session.add(TeamMember(team_id=team_id, user_id=user_id, tenant_id=tenant_id))
        await session.flush()

    @staticmethod
    async def remove_member(
        session: AsyncSession, tenant_id: uuid.UUID, team_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await TeamService._get(session, tenant_id, team_id)
        await session.execute(
            delete(TeamMember).where(
                TeamMember.team_id == team_id,
                TeamMember.user_id == user_id,
                TeamMember.tenant_id == tenant_id,
            )
        )
        await session.flush()
