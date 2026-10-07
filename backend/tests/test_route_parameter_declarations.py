"""The parameter-declaration rule, swept across the WHOLE app.

The defect class (see the long header in ``app/modules/analytics/router.py``)
--------------------------------------------------------------------------
``async def endpoint(limit: int = Query(default=50))`` puts a ``fastapi.params.Query``
object — a pydantic ``FieldInfo``, which is neither an int nor anything the
annotation claims — into the *function's own* ``__defaults__``. FastAPI replaces
it on the HTTP path, so the route answers correctly forever. But a handler is a
plain Python function: any in-process caller that omits the argument receives the
declaration object and forwards it onward. CI run 35959902953 proved the cost —
``analytics_overview`` declared ``low_stock_threshold: int = Query(default=2)``,
a test called it in-process, and the unconverted ``Query(2)`` rode into an
``integer`` bind: ``DataError: invalid input for query argument $1: Query(2)``.

The correct form is
``limit: Annotated[int, Query(ge=1)] = 50`` — identical to FastAPI, a real value
to Python.

What this file adds over the module's own pin
---------------------------------------------
``tests/test_analytics_overview.py::test_route_parameters_default_to_values_not_declarations``
guards ONE router and stays as analytics' own pin. This file generalises it to a
full-app sweep: it walks every ``route.endpoint`` reachable from ``create_app()``
(recursing through FastAPI's lazily-included routers) and refuses any parameter
that defaults to a ``FieldInfo``. No module can reintroduce the pattern without a
red build here.

Two things keep the sweep honest:

* It is a full-app walk, not a grep. ``test_detector_reports_declaration_shapes_only``
  mounts a throwaway router with one bad parameter of each shape and proves the
  detector catches exactly those while leaving the correct ``Annotated`` form and
  a ``Depends`` alone, so neither half can pass vacuously.
* ``test_sweep_is_not_vacuous`` asserts the walk reaches a large endpoint set and
  named routers, because a sweep of an empty route list also passes.

There used to be a third item here: a SHRINK-ONLY ``DEFERRED_DECLARATIONS``
baseline naming the eight ``app/modules/ai/router.py`` sites this lane was told
not to edit while the W4-T3 money lane held them open. The money lane converted
all eight, so the baseline emptied and was deleted — which is what a shrink-only
list is for. The sweep is now unconditional: any route parameter anywhere that
defaults to a declaration fails this file.

DB-free: nothing here opens a connection; ``create_app()`` builds offline.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query
from pydantic.fields import FieldInfo

from app.main import create_app


def _declaration_params(endpoint) -> list[str]:
    """Names of parameters whose default is a FastAPI declaration, not a value.

    ``Query``/``Body``/``Header``/``Cookie`` are ``FieldInfo`` subclasses; a
    ``Depends`` default is not, and neither is a plain ``50`` sitting beside an
    ``Annotated[int, Query(...)]`` annotation.
    """
    return [
        name
        for name, parameter in inspect.signature(endpoint).parameters.items()
        if isinstance(parameter.default, FieldInfo)
    ]


def _iter_endpoints(node, seen: set[int]) -> Iterator:
    """Every endpoint reachable from a route/router node, deduped by identity.

    FastAPI 0.141 defers ``include_router`` into an ``_IncludedRouter`` that
    exposes neither ``.routes`` nor ``.endpoint`` directly — the real router
    hangs off ``include_context.included_router`` — so the walk follows both that
    indirection and the ordinary ``.routes`` list (Starlette mounts, APIRouters).
    """
    endpoint = getattr(node, "endpoint", None)
    if callable(endpoint) and id(endpoint) not in seen:
        seen.add(id(endpoint))
        yield endpoint
    include_ctx = getattr(node, "include_context", None)
    child_router = getattr(include_ctx, "included_router", None) if include_ctx else None
    if child_router is not None:
        yield from _iter_endpoints(child_router, seen)
    for child in getattr(node, "routes", None) or []:
        yield from _iter_endpoints(child, seen)


def _app_offenders(app) -> set[tuple[str, str, str]]:
    """``(module, qualname, param)`` for every declaration-defaulted parameter."""
    seen: set[int] = set()
    offenders: set[tuple[str, str, str]] = set()
    for route in app.routes:
        for endpoint in _iter_endpoints(route, seen):
            for name in _declaration_params(endpoint):
                offenders.add((endpoint.__module__, endpoint.__qualname__, name))
    return offenders


def _where(module: str, qualname: str, param: str) -> str:
    """A file:line-ish locator for the failure message."""
    return f"{module}::{qualname}::{param}"


def test_no_route_parameter_defaults_to_a_declaration() -> None:
    """No endpoint anywhere in the app may default a parameter to a declaration.

    An in-process caller that omits such an argument receives the declaration
    object itself and forwards it into whatever the handler binds it to — the
    failure is a 500 (``DataError`` on the SQL bind), never a caught 400.
    """
    offenders = sorted(_app_offenders(create_app()))

    assert not offenders, (
        "these route parameters default to a FastAPI declaration, which an "
        "in-process caller hands straight into a SQL bind (CI run 35959902953). "
        "Declare them `Annotated[type, Query(...)] = <value>` instead:\n"
        + "\n".join(f"  {_where(*key)}" for key in offenders)
    )


def test_sweep_is_not_vacuous() -> None:
    """The walk must actually reach the mounted surface, or the gate proves nothing.

    A sweep of an empty route list passes against any code base. This asserts the
    walker discovers a large, non-trivial set of endpoints and reaches every
    module whose parameters the sweep converted — analytics' original fix plus
    the full-app lanes — so a green
    ``test_no_route_parameter_defaults_to_a_declaration`` cannot be the artifact
    of a traversal that reached nothing.
    """
    app = create_app()
    seen: set[int] = set()
    endpoints = [ep for route in app.routes for ep in _iter_endpoints(route, seen)]
    assert len(endpoints) > 150, f"sweep reached only {len(endpoints)} endpoints"

    modules = {ep.__module__ for ep in endpoints}
    for owned in (
        "app.modules.ai.router",
        "app.modules.analytics.router",
        "app.modules.automation.router",
        "app.modules.conversations.router",
        "app.modules.customers.router",
        "app.modules.marketing.router",
        "app.modules.operations.router",
        "app.modules.orders.router",
        "app.modules.platform.router",
        "app.modules.privacy.router",
    ):
        assert owned in modules, f"sweep never reached {owned}"


def test_detector_reports_declaration_shapes_only() -> None:
    """Proof the detector discriminates, so neither half of the gate passes empty.

    One bad parameter of each shape (``= Query(1)``, ``= Body(...)``,
    ``= Header("x")``) must be reported; the correct ``Annotated[int, Query] = 2``
    form and a ``= Depends(...)`` parameter must NOT be — even after they are all
    mounted, so the walker itself is exercised against known truth.
    """

    async def bad_query(limit: int = Query(1)):
        return limit

    async def bad_body(name: str = Body(...)):
        return name

    async def bad_header(x_trace: str = Header("x")):
        return x_trace

    async def good_annotated(limit: Annotated[int, Query(ge=0)] = 2):
        return limit

    async def good_depends(user: str = Depends(lambda: "u")):
        return user

    # 1. at the signature level: the detector sees declarations, not values/deps.
    assert _declaration_params(bad_query) == ["limit"]
    assert _declaration_params(bad_body) == ["name"]
    assert _declaration_params(bad_header) == ["x_trace"]
    assert _declaration_params(good_annotated) == []
    assert _declaration_params(good_depends) == []

    # 2. mounted: the full-app walker reports exactly the three offenders and
    #    proves it visited the two correct handlers (not vacuous by omission).
    probe = APIRouter()
    for fn in (bad_query, bad_body, bad_header, good_annotated, good_depends):
        probe.add_api_route(f"/{fn.__name__}", fn, methods=["GET"])
    app = FastAPI()
    app.include_router(probe)

    seen: set[int] = set()
    visited = {ep.__name__ for route in app.routes for ep in _iter_endpoints(route, seen)}
    # A fresh FastAPI() also mounts its own openapi/docs handlers; the probe
    # functions must all be among them, which is what proves the walker reached
    # the two CORRECT handlers rather than the assertion passing by omission.
    assert {"bad_query", "bad_body", "bad_header", "good_annotated", "good_depends"} <= visited

    offenders = {
        (qualname.rpartition(".")[2], param) for _mod, qualname, param in _app_offenders(app)
    }
    assert offenders == {("bad_query", "limit"), ("bad_body", "name"), ("bad_header", "x_trace")}
