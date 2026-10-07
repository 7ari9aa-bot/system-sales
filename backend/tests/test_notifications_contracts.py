"""NOTIFICATIONS surface contracts — typed replies, P7 bounds, and the two
register claims about this module (P2 and P3), verified against the code.

What the register said vs. what the code says today
---------------------------------------------------
**P2** filed two defects: (a) a billing-hosted ``POST /api/v1/notifications``
404'd because its ``platform_router`` was never registered, and (b) "two
different notification contracts, one dead". Both are now resolved — by
DELETION, not by mounting. ``app/modules/billing/router.py``'s own header says
the duplicate was never mounted and was "dead code that would have shadowed the
notifications centre the moment anyone did mount it", and ``app.main`` registers
the live ``modules/notifications/router.py`` exactly once. What is left is the
consequence nobody wrote down: the delete removed the second contract and the
create route with it, so ``POST /api/v1/notifications`` 404s for a NEW reason —
there is no notification-create endpoint at all. That is correct (a client must
not be able to insert a notification into another user's inbox; every real
producer is server-side: the AI gateway, break-glass, automation runs), and it
is pinned below rather than assumed, because "one of these two contracts is
wrong" is exactly the shape that comes back.

**P3** filed ``{"detail": "not found"}`` answered with HTTP 200 on notification
read. Gone: ``NotificationService.mark_read`` raises ``NotFoundError`` and says
so. Pinned below at the handler, with the status the client actually gets.

**P7** filed "negative/unbounded ``limit``/``offset``". ``GET /notifications``
is that row: both parameters reach the service unbounded, and the service caps
only the top (``min(limit, 200)``). ``?limit=-1`` and ``?offset=-1`` arrive at
Postgres as ``LIMIT -1`` / ``OFFSET must not be negative`` — a 500, from a query
string.

The response half: five of the seven routes answered with a bare ``dict`` or
``dict[str, int]``, which OpenAPI renders as an anonymous object, so the bell's
own counts had no contract. All seven are named now.
"""

from __future__ import annotations

import ast
import functools
import pathlib
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.dialects import postgresql

import app.modules.billing.router as billing_router
from app.core.errors import NotFoundError, ValidationError
from app.main import create_app
from app.modules.notifications.router import MarkReadRequest, mark_read
from app.modules.notifications.service import NotificationService

#: The page ceiling the service and the route both honour.
PAGE_MAX = 200

NOTIFICATIONS_MODULE = "app.modules.notifications.router"
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# doubles + openapi readers (same shape as tests/test_operations_contracts.py)
# --------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: tuple = ()) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> tuple:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class RecordingSession:
    """Captures the statements the service would have run, and answers them."""

    def __init__(self, row: Any = None) -> None:
        self.row = row
        self.statements: list[Any] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        self.statements.append(statement)
        return _Result((self.row,) if self.row is not None else ())

    def compiled_params(self) -> dict:
        """The bind values Postgres would receive for the first statement."""
        return dict(self.statements[0].compile(dialect=postgresql.dialect()).params)


def _ctx(session: Any) -> Any:
    return SimpleNamespace(
        session=session,
        tenant_id=uuid.uuid4(),
        user=SimpleNamespace(id=uuid.uuid4()),
    )


def _notification(**overrides: Any) -> Any:
    from datetime import UTC, datetime

    base = {
        "id": uuid.uuid4(),
        "kind": "order_paid",
        "title": None,
        "body": "an order was paid",
        "action_url": None,
        "payload": {},
        "read_at": None,
        "created_at": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    }
    return SimpleNamespace(**{**base, **overrides})


@functools.lru_cache(maxsize=1)
def _app() -> Any:
    return create_app()


@functools.lru_cache(maxsize=1)
def _document() -> dict:
    return _app().openapi()


def _iter_mounted(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """``(mounted_path, APIRoute)`` with the include prefixes accumulated.

    FastAPI 0.141 defers ``include_router`` into an ``_IncludedRouter`` that
    carries the prefix on ``include_context`` rather than on the route, so
    without this a module's routes read as ``/notifications`` and cannot be
    matched against the document a client sees.
    """
    include_ctx = getattr(node, "include_context", None)
    child = getattr(include_ctx, "included_router", None) if include_ctx else None
    if child is not None:
        yield from _iter_mounted(child, prefix + (getattr(include_ctx, "prefix", "") or ""))
    for sub in getattr(node, "routes", None) or []:
        yield from _iter_mounted(sub, prefix)
    if isinstance(node, APIRoute):
        yield prefix + node.path, node


def _mounted_for(module: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for path, route in _iter_mounted(_app()):
        if getattr(route.endpoint, "__module__", None) != module:
            continue
        for method in route.methods or ():
            if method not in {"HEAD", "OPTIONS"}:
                out[(method, path)] = route.endpoint.__name__
    return out


def _named_component(schema: Any) -> str | None:
    ref = (schema or {}).get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    for key in ("items", "additionalProperties"):
        sub = (schema or {}).get(key)
        if isinstance(sub, dict) and sub.get("$ref"):
            return sub["$ref"].rsplit("/", 1)[-1]
    return None


def _success_component(document: dict, method: str, path: str) -> str | None:
    operation = document["paths"][path][method.lower()]
    for status in sorted(operation["responses"]):
        if not status.startswith("2"):
            continue
        content = operation["responses"][status].get("content", {})
        schema = content.get("application/json", {}).get("schema")
        return _named_component(schema)
    return None


def _bounds(schema: Any) -> tuple[int | None, int | None]:
    candidates = [schema, *schema.get("allOf", [])]
    for candidate in candidates:
        if candidate.get("minimum") is not None or candidate.get("maximum") is not None:
            return candidate.get("minimum"), candidate.get("maximum")
    return None, None


def _query_bounds(path: str, name: str, method: str = "get") -> tuple:
    spec = _document()["paths"][path][method]
    param = next(p for p in spec["parameters"] if p["name"] == name and p["in"] == "query")
    return _bounds(param["schema"])


# ==========================================================================
# 1. every route answers with a named schema
# ==========================================================================


def test_every_notification_route_has_a_typed_response() -> None:
    """The bell's counts were ``dict``\\ s: an anonymous body on the wire."""
    document = _document()
    mounted = _mounted_for(NOTIFICATIONS_MODULE)
    assert len(mounted) == 7, f"expected the seven notification routes, got {mounted}"

    untyped = sorted(
        f"{method} {path} ({endpoint})"
        for (method, path), endpoint in mounted.items()
        if _success_component(document, method, path) is None
    )
    assert not untyped, "these routes return a body OpenAPI cannot name:\n  " + "\n  ".join(untyped)


def test_the_unread_and_marked_counters_are_named_fields_not_anonymous_dicts() -> None:
    """``{"count": n}`` and ``{"marked": n}`` are two names for one idea.

    Both were ``dict[str, int]``, so a client had no type to hold and a typo in
    the key ("marked" vs "count") was invisible until a badge stopped moving.
    """
    document = _document()
    unread = document["components"]["schemas"][
        _success_component(document, "GET", "/api/v1/notifications/unread-count")
    ]
    marked = document["components"]["schemas"][
        _success_component(document, "POST", "/api/v1/notifications/mark-read")
    ]
    assert list(unread["properties"]) == ["count"], unread
    assert list(marked["properties"]) == ["marked"], marked
    assert unread["properties"]["count"]["type"] == "integer"
    assert marked["properties"]["marked"]["type"] == "integer"


def test_the_summary_and_digest_bodies_are_structured() -> None:
    """``GET /notifications/summary`` answered ``-> dict``: no keys, no types."""
    document = _document()
    summary_name = _success_component(document, "GET", "/api/v1/notifications/summary")
    digest_name = _success_component(document, "GET", "/api/v1/notifications/digest")
    schemas = document["components"]["schemas"]

    summary = schemas[summary_name]
    assert {"total", "unread", "by_kind"} <= set(summary["properties"]), summary
    kind_ref = summary["properties"]["by_kind"]["items"]["$ref"].rsplit("/", 1)[-1]
    assert {"kind", "total", "unread"} <= set(schemas[kind_ref]["properties"])

    digest = schemas[digest_name]
    assert {"total_unread", "groups"} <= set(digest["properties"]), digest
    group_ref = digest["properties"]["groups"]["items"]["$ref"].rsplit("/", 1)[-1]
    assert {"kind", "count", "latest_at"} <= set(schemas[group_ref]["properties"])


def test_the_typed_response_gate_can_fail() -> None:
    """Proof the gate bites: a ``dict`` route is reported, a model is not."""
    probe = FastAPI()

    @probe.get("/anonymous")
    async def anonymous() -> dict[str, int]:
        return {"count": 1}

    @probe.get("/named")
    async def named() -> MarkReadRequest:
        return MarkReadRequest(ids=[uuid.uuid4()])

    document = probe.openapi()
    assert _success_component(document, "GET", "/anonymous") is None
    assert _success_component(document, "GET", "/named") == "MarkReadRequest"


# ==========================================================================
# 2. P7 — the list's limit/offset
# ==========================================================================


def test_notification_list_pagination_is_bounded_at_the_edge() -> None:
    """``?limit=-1`` and ``?offset=-1`` used to reach the database verbatim."""
    low, high = _query_bounds("/api/v1/notifications", "limit")
    assert (low, high) == (1, PAGE_MAX), (low, high)
    offset_low, offset_high = _query_bounds("/api/v1/notifications", "offset")
    assert offset_low == 0, offset_low
    assert offset_high is not None, "offset needs a ceiling: it pages a bounded list"


async def test_the_service_refuses_a_negative_page_instead_of_emitting_one() -> None:
    """The route is not the only caller that matters.

    ``list_for_user`` capped the TOP (``min(limit, 200)``) and nothing else, so
    an in-process ``limit=-1`` rode into ``LIMIT -1`` and ``offset=-1`` into
    ``OFFSET must not be negative`` — both Postgres errors, both a 500.
    """
    with pytest.raises(ValidationError):
        await NotificationService.list_for_user(None, uuid.uuid4(), uuid.uuid4(), limit=-1)
    with pytest.raises(ValidationError):
        await NotificationService.list_for_user(None, uuid.uuid4(), uuid.uuid4(), offset=-1)


async def test_the_service_caps_an_oversized_page_at_the_documented_max() -> None:
    """A cap that only exists in the route can be walked past in-process."""
    session = RecordingSession()
    await NotificationService.list_for_user(
        session, uuid.uuid4(), uuid.uuid4(), limit=100_000, offset=0
    )
    binds = session.compiled_params()
    assert PAGE_MAX in binds.values(), f"LIMIT was not capped at {PAGE_MAX}: {binds}"
    assert not any(v == -1 for v in binds.values()), binds


async def test_the_service_keeps_a_valid_page_intact() -> None:
    """The clamp must not start eating legitimate pages."""
    session = RecordingSession()
    await NotificationService.list_for_user(
        session, uuid.uuid4(), uuid.uuid4(), limit=50, offset=100
    )
    binds = session.compiled_params()
    assert 50 in binds.values() and 100 in binds.values(), binds


# ==========================================================================
# 3. P3 — the read path answers 404, not 200-with-detail
# ==========================================================================


async def test_mark_read_of_a_gone_notification_is_a_404_not_a_200() -> None:
    """Register P3's exact words: ``{"detail": "not found"}`` with HTTP 200.

    A client marking a notification that had already been deleted believed it
    had worked. ``mark_read`` now raises ``NotFoundError``; this pins both the
    exception and the status it renders as, from the handler outward.
    """
    session = RecordingSession(row=None)
    with pytest.raises(NotFoundError) as excinfo:
        await mark_read(uuid.uuid4(), _ctx(session))
    assert excinfo.value.http_status == 404, "a 200 here is the original defect"
    assert excinfo.value.code == "not_found"
    assert not any("UPDATE" in str(stmt).upper() for stmt in session.statements), (
        "a refused read still stamped a row"
    )


async def test_mark_read_returns_the_row_it_stamped() -> None:
    notif = _notification()
    session = RecordingSession(row=notif)
    out = await mark_read(notif.id, _ctx(session))
    assert out.id == notif.id
    assert out.read_at is not None, "the reply must carry the stamp, not just admit it"


def test_no_notification_route_writes_a_detail_body() -> None:
    """Static sweep: nothing in this module may emit ``{"detail": ...}``.

    ``frontend/src/lib/api.ts`` reads ``body?.error?.message ?? body?.detail``,
    so a ``detail`` written by a route is the legacy shape re-entering through
    the one door the client still opens for it.
    """
    offenders: list[str] = []
    for path in sorted((BACKEND_ROOT / "app" / "modules" / "notifications").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "detail":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, "raise a DomainError and let the handler write the body: " + ", ".join(
        offenders
    )


# ==========================================================================
# 4. P2 — one notification contract, mounted once
# ==========================================================================


def test_the_notifications_surface_is_mounted_exactly_once() -> None:
    """Two routers answering ``/api/v1/notifications*`` is the P2 shadowing bug.

    Whichever was included LAST won, and the loser's tests stayed green because
    they imported the router directly.
    """
    seen: dict[str, list[str]] = {}
    for path, route in _iter_mounted(_app()):
        if path.startswith("/api/v1/notifications"):
            for method in route.methods or ():
                seen.setdefault(f"{method} {path}", []).append(route.endpoint.__name__)
    duplicated = {key: names for key, names in seen.items() if len(names) > 1}
    assert not duplicated, f"two handlers claim the same route: {duplicated}"
    assert len(seen) == 7, sorted(seen)


def test_the_billing_module_no_longer_ships_a_second_notifications_router() -> None:
    """The dead half of P2, pinned as DELETED rather than merely unmounted.

    An unmounted router is a trap rather than dead weight: the next
    ``include_router`` sweep picks it up, and because its paths are identical it
    shadows the live centre while its own tests keep passing against it.
    """
    stray_routers = [
        f"{name} (prefix={value.prefix!r})"
        for name, value in vars(billing_router).items()
        if isinstance(value, APIRouter) and "/notifications" in (value.prefix or "")
    ]
    assert not stray_routers, "a second /notifications router is back: " + ", ".join(stray_routers)
    # The module's own docstring records the deletion; what must not come back is
    # a ROUTER. Asserting on prose would fail on the sentence that explains the
    # fix, which is a worse signal than not checking at all.
    assert billing_router.__doc__ and "never mounted" in billing_router.__doc__


def test_there_is_no_notification_create_route_and_that_is_deliberate() -> None:
    """P2's literal claim — ``POST /api/v1/notifications`` 404s — still holds,
    for a different reason, and the reason must stay a decision.

    Every producer is server-side (``NotificationService.create`` is called by
    the AI gateway, break-glass and automation). A client-writable create would
    let any user push a row into another user's inbox in the same tenant. So the
    404 is correct; what was wrong was having it be an accident.
    """
    document = _document()
    assert "post" not in document["paths"]["/api/v1/notifications"]
    assert hasattr(NotificationService, "create")
