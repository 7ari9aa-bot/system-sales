"""A write must be committed before the client is told it succeeded.

FastAPI runs a ``yield`` dependency's exit code AFTER the response has been sent, so a session
committed only in that exit leaves a window where the client holds its 201 while the row is
still invisible to every other connection. The live POS flow walks straight into it — create the
profile, then create the register on it — and the browser suite showed exactly that: two
requests 22 ms apart, a 201 and then ``pos profile <id> not found`` for the row the 201 was
about.

The ordering is what matters, so the tests record it instead of querying: the endpoint writes,
the route handler commits, and only then does the response leave. A session stub keeps this a
pure framework test — no database, no driver, nothing to install.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from app.core.routing import CommitBeforeResponseRoute


class StubSession:
    """Just the two things the route handler asks of a session."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self._open = True

    def in_transaction(self) -> bool:
        return self._open

    async def commit(self) -> None:
        self._log.append("commit")
        self._open = False


def _app(*, commit_in_route: bool, fail: bool = False) -> tuple[FastAPI, list[str]]:
    log: list[str] = []
    app = FastAPI()
    router = APIRouter(route_class=CommitBeforeResponseRoute) if commit_in_route else APIRouter()

    async def get_db(request: Request) -> AsyncIterator[StubSession]:
        session = StubSession(log)
        request.state.db_session = session
        yield session

    @router.post("/rows")
    async def create(session: StubSession = Depends(get_db)) -> dict[str, Any]:
        log.append("endpoint")
        if fail:
            raise HTTPException(status_code=422, detail="nothing was written")
        return {"ok": True}

    app.include_router(router)

    @app.middleware("http")
    async def watch(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        log.append("answered")  # the client has its answer from here on
        return response

    return app, log


async def _post(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post("/rows")


@pytest.mark.asyncio
async def test_the_commit_lands_before_the_answer() -> None:
    app, log = _app(commit_in_route=True)
    assert (await _post(app)).status_code == 200
    assert log == ["endpoint", "commit", "answered"]


@pytest.mark.asyncio
async def test_committing_only_in_the_dependency_exit_answers_first() -> None:
    """The bug this route class exists to close, pinned so it cannot come back."""
    app, log = _app(commit_in_route=False)
    assert (await _post(app)).status_code == 200
    assert log == ["endpoint", "answered"]


@pytest.mark.asyncio
async def test_a_refused_write_commits_nothing() -> None:
    app, log = _app(commit_in_route=True, fail=True)
    assert (await _post(app)).status_code == 422
    assert "commit" not in log
