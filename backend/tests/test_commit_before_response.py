"""A write must be durable before the client is told it succeeded.

FastAPI runs a ``yield`` dependency's exit code AFTER the response has been sent, so a session
committed only in that exit leaves a window in which the client holds its 201 while the row is
still invisible to every other connection. The live POS flow walks straight into it — create the
profile, then create the register on it — and the browser suite saw exactly that: two requests
22 ms apart, a 201 and then ``pos profile <id> not found`` for the row the 201 was about.

The test observes the ordering where it actually happens: a middleware reads the row from a
SECOND connection at the moment the response is being returned, before the dependency's exit
runs. Committed-in-the-route means the row is already there; committed-in-the-exit means it is
not.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.routing import CommitBeforeResponseRoute


async def _build(
    db_path: Path, *, commit_in_route: bool
) -> tuple[FastAPI, async_sessionmaker[AsyncSession], dict[str, Any]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        # WAL: a reader on another connection sees the last COMMITTED state and never blocks, so
        # the observation below is about commit ordering and nothing else.
        await conn.execute(sa.text("PRAGMA journal_mode=WAL"))
        await conn.execute(sa.text("CREATE TABLE rows (v INTEGER NOT NULL)"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seen: dict[str, Any] = {}

    app = FastAPI()
    router = APIRouter(route_class=CommitBeforeResponseRoute) if commit_in_route else APIRouter()

    async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            request.state.db_session = session
            async with session.begin():
                yield session

    @router.post("/rows")
    async def create(session: AsyncSession = Depends(get_db)) -> dict[str, bool]:
        await session.execute(sa.text("INSERT INTO rows (v) VALUES (1)"))
        return {"ok": True}

    app.include_router(router)

    @app.middleware("http")
    async def watch(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if request.method == "POST":
            # The dependency's exit has NOT run yet: this is the client's view of the row.
            async with factory() as other:
                seen["count_when_answered"] = (
                    await other.execute(sa.text("SELECT count(*) FROM rows"))
                ).scalar()
        return response

    return app, factory, seen


@pytest.mark.asyncio
async def test_the_row_is_committed_before_the_client_gets_the_answer(tmp_path: Path) -> None:
    app, _factory, seen = await _build(tmp_path / "durable.db", commit_in_route=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/rows")).status_code == 200
    assert seen["count_when_answered"] == 1, (
        "the answer went out before the write was committed: a client that reads the row it "
        "just created gets a 404"
    )


@pytest.mark.asyncio
async def test_committing_only_in_the_dependency_exit_leaves_the_window_open(
    tmp_path: Path,
) -> None:
    """The bug this route class exists to close, pinned so it cannot come back."""
    app, _factory, seen = await _build(tmp_path / "late.db", commit_in_route=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/rows")).status_code == 200
    assert seen["count_when_answered"] == 0
