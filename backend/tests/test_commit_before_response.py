"""A write is in the database before the client is told it happened.

FastAPI runs a ``yield`` dependency's exit AFTER the response is sent, so ``get_db``'s
``async with session.begin()`` commits too late: a second request can arrive in that window and
404 on the row the first request just answered 201 for. The live suite met exactly that —
``product <id> not found``, ``register <id> not found`` — against a database that held the row.

``CommitBeforeResponseRoute`` was written for this and then set on the ``/api/v1`` router only.
FastAPI keeps an included router's own ``APIRoute`` objects, so the parent's ``route_class``
reached no endpoint at all and the guarantee was inert. These tests pin the mechanism that does
reach every route.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.core.routing import (
    CommitBeforeResponseMiddleware,
    _has_pending_writes,
)


class FakeSession:
    """The two things the middleware asks of a session: is a transaction open, commit it."""

    def __init__(
        self, *, in_transaction: bool = True, pending: bool = True, wrote: bool = False
    ) -> None:
        self._in_transaction = in_transaction
        self.new = [object()] if pending else []
        self.dirty: list[object] = []
        self.deleted: list[object] = []
        # ``after_flush`` sets this; a SAVEPOINT flush empties ``new`` while the write is
        # still uncommitted.
        self.info: dict[str, object] = {"wrote": True} if wrote else {}
        self.commits = 0
        self.committed_before_body = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    async def commit(self) -> None:
        self.commits += 1
        self._in_transaction = False


def _run(app, scope_extra=None):
    """Drive one ASGI request through the middleware and record the message order."""
    sent: list[str] = []
    scope = {"type": "http", "state": dict(scope_extra or {})}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message["type"])

    asyncio.run(CommitBeforeResponseMiddleware(app)(scope, receive, send))
    return sent


def test_commits_before_the_response_starts():
    session = FakeSession()
    order: list[str] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        order.append("body")
        await send({"type": "http.response.body", "body": b"{}"})

    sent = _run(app, {"db_session": session})

    assert session.commits == 1, "the write must be durable before the client is answered"
    assert sent == ["http.response.start", "http.response.body"]
    assert order == ["body"]


def test_a_read_only_request_is_not_committed():
    """A stream keeps reading through its session; closing the transaction drops the tenant GUC."""
    session = FakeSession(pending=False)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    _run(app, {"db_session": session})

    assert session.commits == 0
    assert session.in_transaction(), "a read must leave the transaction open"


def test_a_request_that_raises_commits_nothing():
    session = FakeSession()

    async def app(scope, receive, send):
        raise RuntimeError("endpoint blew up")

    with pytest.raises(RuntimeError):
        _run(app, {"db_session": session})

    assert session.commits == 0


def test_a_request_without_a_session_passes_through():
    sent: list[str] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message["type"])

    asyncio.run(CommitBeforeResponseMiddleware(app)({"type": "http"}, receive, send))
    assert sent == ["http.response.start", "http.response.body"]


def test_lifespan_traffic_is_ignored():
    seen: list[str] = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(CommitBeforeResponseMiddleware(app)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_pending_writes_helper():
    assert _has_pending_writes(FakeSession(pending=True))
    assert not _has_pending_writes(FakeSession(pending=False))
    assert not _has_pending_writes(object())


def test_a_write_flushed_inside_a_savepoint_still_counts():
    """``session.begin_nested()`` + ``flush()`` moves the row out of ``session.new``.

    Catalog's add_variant writes that way, so the identity-map heuristic read the request as
    read-only, the early commit was skipped, and the client's next request 404'd on the row it
    had just been told existed (live-api: "variant <id> not found", fixed only by a retry).
    """
    session = FakeSession(pending=False, wrote=True)
    assert _has_pending_writes(session), "a flushed write is still an uncommitted write"

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    _run(app, {"db_session": session})
    assert session.commits == 1, "the savepoint write must be durable before the client is answered"


def test_an_event_stream_is_never_committed_under_itself():
    """A stream keeps reading through the same session; committing at response start would
    close the transaction under it, drop the tenant GUC, and RLS would hide every row."""
    session = FakeSession(wrote=True)

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": b"data: 1\n\n"})

    _run(app, {"db_session": session})
    assert session.commits == 0
    assert session.in_transaction()


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="the app needs 3.12+ syntax (PEP 695); this ratchet runs where the app runs",
)
def test_every_api_route_is_behind_the_middleware():
    """The ratchet: the app must install it, or the guarantee is inert again."""
    from app.main import app

    installed = {m.cls.__name__ for m in app.user_middleware if getattr(m, "cls", None)}
    assert "CommitBeforeResponseMiddleware" in installed
