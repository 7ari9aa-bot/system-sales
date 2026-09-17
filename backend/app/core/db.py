"""Async database engine, sessions, and tenant GUC binding.

Production notes:
- With a transaction-mode pooler (Supabase pgbouncer :6543) the tenant GUC must
  be set with SET LOCAL inside each transaction — bind_tenant() does exactly that.
- Migrations use the direct connection (:5432), workers/API use the pooler.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

TENANT_GUC = "app.tenant_id"


class Base(DeclarativeBase):
    """Declarative base for every ORM model in all modules."""


def _create_engine() -> AsyncEngine:
    # statement_cache_size=0 is REQUIRED behind transaction-mode poolers
    # (Supabase Supavisor :6543, pgbouncer) — prepared statements are not
    # supported there and raise DuplicatePreparedStatementError otherwise.
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )


engine: AsyncEngine = _create_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a DB session."""
    async with SessionLocal() as session:
        yield session


async def bind_tenant(session: AsyncSession, tenant_id: UUID | str) -> None:
    """Bind the tenant for RLS policies on the current transaction.

    set_config(..., is_local := true) is transaction-scoped exactly like
    SET LOCAL (required behind transaction-pooled connections) — but unlike
    SET LOCAL it accepts bind parameters (SET is a utility statement and
    rejects $1 placeholders).
    Call inside an active transaction (session.begin() / tenant_scope()).
    """
    await session.execute(
        text("SELECT set_config(:guc, :tenant_id, true)"),
        {"guc": TENANT_GUC, "tenant_id": str(tenant_id)},
    )
