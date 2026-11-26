"""Routing that keeps a write durable before the client is told it happened.

FastAPI runs the exit code of a ``yield`` dependency AFTER the response has been sent, so
``get_db``'s ``async with session.begin(): yield session`` used to COMMIT after the client
already held its 201. Anything that reads the row it just created, in a second request, could
arrive inside that window and get a 404 for something that plainly exists a moment later. The
live POS flow does exactly that — create the profile, then create the register on it — and it
was the intermittent ``pos profile <id> not found`` in the browser suite: two requests 22 ms
apart, one 201 and one 404, against a database that had the row the whole time.
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


class CommitBeforeResponseRoute(APIRoute):
    """Commit the request's transaction before the response body leaves the process.

    ``get_db`` publishes its session on ``request.state.db_session``; this route handler closes
    the transaction here, while the response object is still in our hands. The dependency's own
    exit then finds no open transaction and does nothing, so nothing commits twice.

    An endpoint that raises never reaches this code: the exception propagates, the dependency's
    exit rolls back, and a failed request writes nothing — the same guarantee as before.
    """

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            if isinstance(response, StreamingResponse):
                # A stream (SSE) keeps reading through the session while it runs; committing here
                # would close the transaction under it and the next read would open a fresh one
                # with no tenant GUC bound — RLS would hide every row. Streams keep the old
                # ordering: they answer first, commit at exit.
                return response
            session = getattr(request.state, "db_session", None)
            if session is not None and session.in_transaction():
                await session.commit()
            return response

        return handler


def _has_pending_writes(session: object) -> bool:
    """Does this session hold changes that are not in the database yet?

    Read-only work never needs the early commit, and for a stream it is actively wrong: the
    endpoint keeps reading through the same session while it sends, so closing the transaction
    under it would drop the tenant GUC and RLS would hide every row from the next read.
    """
    new = getattr(session, "new", None)
    dirty = getattr(session, "dirty", None)
    deleted = getattr(session, "deleted", None)
    if new is None or dirty is None or deleted is None:
        return False
    return bool(new or dirty or deleted)


class CommitBeforeResponseMiddleware:
    """The same guarantee as ``CommitBeforeResponseRoute``, for every route the app serves.

    The route class is set on the ``/api/v1`` router, but FastAPI builds a module router's routes
    with THAT router's class: ``include_router`` keeps the included ``APIRoute`` objects, so the
    parent's ``route_class`` never reached a single endpoint. The guarantee was inert — which is
    why the browser suite kept meeting "product <id> not found" and "register <id> not found"
    on rows the API had answered 201 for a few milliseconds earlier.

    This middleware closes the window where it actually exists: at ``http.response.start``, after
    the endpoint returned and before the first byte leaves the process, while ``get_db``'s
    transaction is still open. It commits only when the session holds pending writes, so a
    read-only request — and a streaming one — is untouched.
    """

    def __init__(self, app: object) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_committing_first(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                await _commit_pending_writes(scope)
            await send(message)

        await self.app(scope, receive, send_committing_first)


async def _commit_pending_writes(scope) -> None:  # type: ignore[no-untyped-def]
    state = scope.get("state") or {}
    session = state.get("db_session")
    if session is None:
        return
    in_transaction = getattr(session, "in_transaction", None)
    if not (callable(in_transaction) and in_transaction()):
        return
    if not _has_pending_writes(session):
        return
    try:
        await session.commit()
    except Exception:  # pragma: no cover - the response is already being sent
        # Never swallow silently: a failed commit here means the client is about to be told a
        # write succeeded that is not in the database. The request log carries the trace.
        logger.exception("commit-before-response failed")
