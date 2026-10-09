"""Shared test fixtures.

DB-backed tests run against a REAL PostgreSQL as the `sales_app` role, with RLS
enforced, but every test executes inside a transaction that is rolled back at
the end — so tests are isolated and never leave data behind.

**The connected ROLE matters, not just the database.** `DATABASE_URL_APP_ADMIN`
must point at `sales_app`, which `scripts/provision.py` creates without
BYPASSRLS. It previously pointed at `postgres` in CI, and `postgres` has
`rolbypassrls = true` — so RLS was silently NOT enforced for the whole suite.
That is how `scheduled_jobs`, a FORCE-RLS table in production, was written to by
an unbound worker for its entire life without a single red build: the tests that
should have caught it were running as a role that ignores the policy.

If you point this at a superuser or a BYPASSRLS role, every RLS test becomes
vacuous. `test_scheduler_rls.py` asserts the role does not bypass RLS and skips
loudly if it does, so the gap is visible rather than silent.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

# Tests are not production. `environment` defaults to "production" (the secure
# direction — an unset ENVIRONMENT must not silently skip the config checks), so
# the suite declares itself local explicitly. `setdefault` so a developer can
# still point it at "staging" deliberately. Must run before `get_settings()` is
# first called, because it is lru_cached.
os.environ.setdefault("ENVIRONMENT", "local")
# Keep token primitives realistic in tests without reusing a deployment key.
os.environ.setdefault("JWT_SECRET", "pytest-only-hmac-key-longer-than-thirty-two-bytes")

# The suite is HERMETIC: a developer's `backend/.env` must never leak into a
# test run, because tests that read settings (CORS origins, secrets envelope,
# integration verify routes) then depend on THIS machine's file, not on the
# committed contract. CI has no .env, so a green CI / red laptop split stays
# invisible until someone local runs the suite — which is exactly how the
# 413-CORS, SecretKeyError, and config-hardening failures reproduced here.
# Pointing `env_file` at a path that does not exist is the supported way to
# disable the file source without forking a second Settings class.
if not os.environ.get("PYTEST_ALLOW_DOTENV"):
    os.environ["PYTEST_DOTENV_DISABLED"] = "1"
    import app.core.config as _config

    _config.Settings.model_config["env_file"] = None

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.identity.models import Role, Tenant, TenantUser, User


@pytest.fixture(scope="session")
def db_url() -> str:
    url = get_settings().database_url_app_admin or get_settings().database_url_app
    if not url:
        pytest.skip("no app database URL configured (DATABASE_URL_APP_ADMIN)")
    return url


@pytest.fixture
def _engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    yield engine


@pytest.fixture
async def db(_engine) -> AsyncIterator[AsyncSession]:
    """Per-test transactional session — rolled back, nothing persists."""
    try:
        async with _engine.connect() as conn:
            trans: AsyncConnection = await conn.begin()
            factory = async_sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            async with factory() as session:
                yield session
            await trans.rollback()
    finally:
        await _engine.dispose()


@pytest.fixture
async def app_sessions_on_test_connection(monkeypatch, db):
    """Bind the APP's own session factory to the test connection.

    Some production paths DELIBERATELY open their own short-lived session so their
    writes survive the request rollback that follows a rejection —
    `_revoke_family_on_reuse` and `record_security_event` both do, and that design
    is correct. It is also untestable by default, for two separate reasons:

    1. The app's engine is process-wide and bound to whichever event loop created
       it, while pytest-asyncio gives every test a fresh loop — so the connection
       raises RuntimeError. (In production there is one loop, so this is purely a
       harness artifact.)
    2. Even once it connects, a separate connection cannot see THIS test's
       uncommitted rows, so an UPDATE against them matches nothing.

    Binding the factory to the test connection fixes both at once: same loop, same
    transaction.

    Patched through `get_sessionmaker`, not `SessionLocal`: the latter is produced
    by `app/core/db.py`'s `__getattr__`, and restoring it by assignment would leave
    a real attribute permanently shadowing the lazy one.
    """
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return factory


class TenantCtx:
    """A disposable tenant + owner user bound into the request context."""

    def __init__(self, session: AsyncSession, tenant: Tenant, user: User, role: Role):
        self.session = session
        self.tenant = tenant
        self.user = user
        self.role = role

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id


@pytest.fixture
async def tenant_ctx(db: AsyncSession) -> AsyncIterator[TenantCtx]:
    """Create tenant + owner (owner role) and bind tenant for RLS."""
    role = (await db.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()

    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Test Tenant")
    user = User(
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Test Owner",
    )
    db.add_all([tenant, user])
    await db.flush()
    # Bind the user GUC so the self-access policy on tenant_users allows
    # creating the owner's own membership row.
    await db.execute(sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)})
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    await db.flush()

    await bind_tenant(db, tenant.id)
    ctx = TenantCtx(db, tenant, user, role)
    yield ctx
    # rollback handled by the db fixture
