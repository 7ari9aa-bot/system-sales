"""Async database engine, sessions, and tenant GUC binding.

Production notes:
- With a transaction-mode pooler (Supabase pgbouncer :6543) the tenant GUC must
  be set with SET LOCAL inside each transaction — bind_tenant() does exactly that.
- Migrations use the direct connection (:5432), workers/API use the pooler.

The engine is built LAZILY. It used to be created at module scope
(`engine = _create_engine()`), which made *importing* this module require a fully
valid production configuration. So `from app.core.db import bind_tenant` inside
an ops script raised "JWT_SECRET must be set in environment 'production'" — a
secret the script never used. Importing a module should not require a deploy's
worth of secrets; only USING a session should.

Access the engine through get_engine() / get_sessionmaker(), or through the
module-level `engine` / `SessionLocal` names, which resolve lazily via PEP 562
so every existing `from app.core.db import SessionLocal` keeps working.
"""

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


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine() -> AsyncEngine:
    # statement_cache_size=0 is REQUIRED behind transaction-mode poolers
    # (Supabase Supavisor :6543, pgbouncer) — prepared statements are not
    # supported there and raise DuplicatePreparedStatementError otherwise.
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )


def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use.

    Deliberately not cached at import: settings are validated when the engine is
    built, so a misconfigured deploy still fails closed — just at first database
    access rather than at import.
    """
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the lazily created engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def dispose_engine() -> None:
    """Close the pool and forget it. Safe to call when the engine was never built.

    Tests and scripts call this to release connections; the next get_engine()
    rebuilds from the current settings.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def __getattr__(name: str):
    """Resolve `engine` / `SessionLocal` on first access (PEP 562).

    `from app.core.db import SessionLocal` triggers this, so the call sites stay
    unchanged while the engine is only built when something actually needs it.
    """
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_sessionmaker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
