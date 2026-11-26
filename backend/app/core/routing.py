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

from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.responses import StreamingResponse


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
