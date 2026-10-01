"""Reachability guard for ``app/modules/**`` — the mirror of the core guard.

``tests/test_no_dead_core_modules.py`` watches ``app.core.*`` only. The v10
external review found that ``app/modules/platform/dr.py``,
``app/modules/notifications/digest.py`` and ``app/modules/catalog/external/*``
had ZERO callers outside their own tests and CI could not see it, because none
of them lives under ``app.core``. That is the repo's dominant failure mode —
"complete, unit-tested, imported by nothing" — recurring a fourth time in two
waves. This file closes the same blind spot for the ``app/modules`` tree.

The technique, restated for modules
-----------------------------------
A module member file is *reachable* if some entry point the platform actually
runs imports it, directly or transitively. Entry points ("roots") are:

    ``app/main.py``        the ASGI composition root (wires every router)
    ``app/workers/run.py`` the worker-pool composition root
    ``scripts/**``         operational/provisioning entry points
    ``migrations/**``      alembic env + version modules (models must be
                           importable for the schema, exactly as the core
                           guard accepts ``app.core.model_registry``)

Reachability is the transitive closure of the import graph over those roots:
``main -> router -> service -> engine`` makes the engine reachable. A file only
imported by another file that is itself unreachable stays unreachable — which
is precisely how "the whole feature is dead" is caught, not just one leaf.

Imports (``import`` / ``from ... import``) are what actually bind a module into
the running application, so — like the core guard — this is an AST scan, not a
grep guess. No database, no Redis, no app import: it runs locally.

Two directions, as in the core guard
------------------------------------
``KNOWN_DEAD_MODULES`` records, with a reason, the module files that are dead
TODAY. Asserting they are still unreachable is what proves the detector can
report "dead"; a detector that returned a caller for everything would pass the
positive half vacuously. Every OTHER module file must be reachable — that is
the regression guard: if a refactor orphans one, this test goes red instead of
shipping silent dead code.

Wiring a dead module is the intended signal: implement its caller, delete its
entry here, and the positive assertion keeps it wired from then on.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

import pytest

# The backend package root: <repo>/backend/tests/test_no_dead_modules.py
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The tree under audit: every non-empty module member file must be reachable.
MODULES_DIR = BACKEND_ROOT / "app" / "modules"

# Source roots scanned for imports. ``app`` is the running product; ``scripts``
# and ``migrations`` are operational entry points whose imports count, exactly
# as ``tests/test_no_dead_core_modules.py`` justifies.
SOURCE_ROOTS: tuple[str, ...] = ("app", "scripts", "migrations")

# Composition roots: dotted module names the platform boots directly. Anything
# reachable from these is live product code.
ROOT_MODULES: frozenset[str] = frozenset(
    {
        "app.main",
        "app.workers.run",
    }
)

# Module files with ZERO reachable importers today, and why. Kept rather than
# deleted: a deletion is the owner's call, and a wrong deletion is unrecoverable.
# Nothing here sits in a path owned by a concurrent agent: each is a feature
# genuinely awaiting its caller, honestly recorded rather than deleted.
KNOWN_DEAD_MODULES: dict[str, str] = {
    # Sales Intelligence analytics layer (spec §5-11) — pure, LLM-free
    # contracts and math: the metric contracts, the exact midpoint drivers,
    # the maturity classifier, the number policy, the confidence engine, and
    # the two validators. Unit-tested; their CALLERS are the query compiler
    # and the sales-intelligence agent loop (next phase), per the spec's
    # dependency order (Phase 1 contracts before Phase 4+ engines).
    "app.modules.analytics.contracts": "SI Phase 1 contracts — compiler lands next.",
    "app.modules.analytics.drivers": "SI Phase 5 engine — compiler + agent land later.",
    "app.modules.analytics.maturity": "SI Phase 3/6 — maturity curves consumer lands later.",
    "app.modules.analytics.numbers": "SI Phase 9 number policy — response path lands later.",
    "app.modules.analytics.confidence": "SI Phase 8 engine — findings builder lands later.",
    "app.modules.analytics.validators": "SI Phase 8/9 gates — builders land later.",
    "app.modules.analytics.coverage": "SI Phase 7 controller — agent loop lands later.",
    "app.modules.analytics.semantic": "SI Phase 3 registry — the compiler consumes it (same wave).",
    "app.modules.analytics.compiler": "SI Phase 4 compiler — the capability layer lands next.",
    "app.modules.analytics.engines": "SI Phase 5 anomaly engine — the capability layer lands next.",
    "app.modules.analytics.capabilities": "SI Phase 6 capabilities — the agent loop lands next.",
    "app.modules.analytics.evidence": "SI Phase 6 pack builder — the agent loop lands next.",
    "app.modules.analytics.findings": "SI Phase 8 builder — the agent loop lands next.",
    # Customer Agent M2 foundations (§8 build order). The state engine IS
    # wired (hooks' photo delivery); the referent resolver and turn intake
    # are the next wave's caller surface — the turn coordinator wires them
    # into AgentRunner alongside the existing context builder. Unit-tested
    # and awaiting that caller, honestly recorded rather than half-wired.
    "app.modules.ai.agents.customer.referents": (
        "§8 referent resolver (التاني/اللي فات over shown_items) — unit-"
        "tested; the M2 turn coordinator is its caller, next wave."
    ),
    "app.modules.ai.agents.customer.intake": (
        "§8 turn intake/normalization (text/photo/voice into InboundTurn) — "
        "unit-tested; the M2 turn coordinator is its caller, next wave."
    ),
    # §166 / ADR-042 storm-suppression write path. Wiring it correctly is a
    # feature, not a one-line call: NotificationService.create() returns the
    # Notification row every caller already depends on, and the aggregator's
    # hold side (add_to_digest) needs a matching FLUSH side — a scheduled
    # worker that delivers a pending digest as one notification. No such
    # worker exists, so a partial wire would silently DROP held notifications,
    # which is worse than dead code. Retained pending that fan-out+flush work;
    # the tables it maps (notification_digests) already exist (f9b0c1d2e3f4).
    "app.modules.notifications.digest": (
        "§166 digest/aggregation. Hold-side only; needs a companion digest-"
        "flush worker before it can be wired without dropping notifications. "
        "Imported today by nothing but tests/test_notifications_digest_import."
    ),
    # §161 / ADR-038 external-commerce feature (Shopify/WooCommerce/CSV). The
    # SourceOfTruthPolicy model backs a migration-created table and every half
    # is unit-tested, but no route or worker yet constructs an adapter — that
    # needs a per-tenant connector-config surface that stores the shop's
    # credentials (Integration) and drives sync. Recorded, not deleted, until
    # that intake exists. (The CSV half of §161 is now live: it is reached from
    # the catalog router's ``/imports/*`` intake, so it is no longer listed here.)
    "app.modules.catalog.external.shopify_adapter": (
        "§161 Shopify sync. No connector-config route/worker constructs a "
        "ShopifyAdapter yet; sync_products already delegates to the live "
        "CatalogService.upsert_from_external, so only the intake is missing."
    ),
    "app.modules.catalog.external.source_of_truth": (
        "§161 source-of-truth policy model + service. Reached only by "
        "shopify_adapter (itself dead) and its tests; kept with it so the "
        "feature is not half-deleted. Table source_of_truth_policies exists."
    ),
}


def _module_name_for(path: pathlib.Path) -> str:
    """Dotted module name for a source file; ``__init__.py`` maps to its package."""
    parts = list(path.relative_to(BACKEND_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _referenced_names(tree: ast.AST, module: str, is_package: bool) -> set[str]:
    """Every dotted name this file binds via import statements.

    ``import a.b.c`` yields a.b.c plus every package prefix (importing a module
    executes its parent packages); ``from a.b import c`` yields a.b and a.b.c.
    Both spellings of the same dependency are recorded so the closure follows
    either.
    """
    names: set[str] = set()

    def add_with_prefixes(dotted: str) -> None:
        bits = dotted.split(".")
        for i in range(1, len(bits) + 1):
            names.add(".".join(bits[:i]))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_with_prefixes(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".") if is_package else module.split(".")[:-1]
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                target = ".".join([*base, node.module]) if node.module else ".".join(base)
            else:
                target = node.module or ""
            if not target:
                continue
            add_with_prefixes(target)
            for alias in node.names:
                if alias.name != "*":
                    names.add(f"{target}.{alias.name}")
    return names


def _iter_source_files() -> Iterator[pathlib.Path]:
    """Non-test Python files under the source roots (package inits included)."""
    for root in SOURCE_ROOTS:
        base = BACKEND_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                yield from ()
                continue
            yield path


def _module_dependencies() -> dict[str, set[str]]:
    """Dotted module name -> set of dotted names it binds via imports."""
    deps: dict[str, set[str]] = {}
    for path in _iter_source_files():
        module = _module_name_for(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a blind detector is worse than a red test
            raise AssertionError(f"cannot parse {path}: {exc}") from exc
        referenced = _referenced_names(tree, module, path.name == "__init__.py")
        referenced.discard(module)
        deps.setdefault(module, set()).update(referenced)
    return deps


def reachable_modules() -> set[str]:
    """Transitive closure of the import graph from the composition roots."""
    deps = _module_dependencies()
    reachable: set[str] = set()
    stack = [name for name in ROOT_MODULES if name in deps]
    # scripts/** and migrations/** files are themselves entry points run by an
    # operator or alembic — treat every module there as a root.
    stack += [
        name
        for name in deps
        if name.startswith("scripts") or name.startswith("migrations")
    ]
    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        stack.extend(deps.get(name, ()))
    return reachable


def _candidate_module_files() -> list[pathlib.Path]:
    """Every non-empty module member file (package ``__init__.py`` excluded)."""
    files: list[pathlib.Path] = []
    for path in sorted(MODULES_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name == "__init__.py":
            # A package init runs whenever the package is imported; flagging an
            # (often docstring-only) init as dead would be noise, not signal.
            continue
        files.append(path)
    return files


def dead_module_files() -> list[str]:
    """Dotted names of unreachable module member files not on the allow-list."""
    reachable = reachable_modules()
    dead: list[str] = []
    for path in _candidate_module_files():
        module = _module_name_for(path)
        if module in KNOWN_DEAD_MODULES:
            continue
        if module not in reachable:
            dead.append(module)
    return dead


def test_every_module_file_is_reachable_or_recorded() -> None:
    """A module file imported by nothing the platform runs is silent dead code.

    This is the guard the core detector missed: a module orphaned from every
    router, worker and script passes its own unit tests forever while shipping
    unused. Fix by wiring a real caller (preferred — routers, workers and
    permission-checked routes already exist for most of these) or, only when
    deletion would lose a spec'd feature that is not yet scheduled, record it
    in ``KNOWN_DEAD_MODULES`` with the reason.
    """
    dead = dead_module_files()
    assert not dead, (
        "unreachable app/modules file(s) with no caller outside their tests:\n  "
        + "\n  ".join(dead)
        + "\nEach is imported (directly or transitively) by nothing in the "
        "composition roots. Wire it behind a live route/worker, or add it to "
        "KNOWN_DEAD_MODULES with the reason if it is a known feature awaiting "
        "its caller."
    )


@pytest.mark.parametrize("module", sorted(KNOWN_DEAD_MODULES))
def test_known_dead_module_files_have_no_reachable_importer(module: str) -> None:
    """The allow-list must be honest: these are still, in fact, dead.

    If this fails because someone wired the module, that is the guard working —
    delete the entry so the positive test takes over and keeps it wired.
    """
    assert module not in reachable_modules(), (
        f"{module} is recorded as dead but is now reachable. Remove it from "
        f"KNOWN_DEAD_MODULES so test_every_module_file_is_reachable_or_recorded "
        f"keeps it wired."
    )


def test_detector_distinguishes_wired_from_dead() -> None:
    """Proof the detector discriminates, so neither half can pass vacuously.

    A router is the clearest wired case (``main`` imports every one); a member
    of a wholly-unimported feature is the clearest dead case. Both directions
    are pinned here plus an impossible name, so the wired/dead split above is
    known to be a real measurement rather than an always-true or always-false
    predicate.
    """
    reachable = reachable_modules()
    assert "app.modules.identity.router" in reachable, (
        "detector found no path to a router main.py wires — the closure is broken"
    )
    assert "app.modules.identity.deps" in reachable, (
        "detector found no path to a service-layer dependency of a live router"
    )
    # A file that only its own tests import cannot be reached from a root.
    assert "app.modules.notifications.digest" not in reachable, (
        "detector reached a module nothing but its tests imports — the "
        "transitive closure is over-permissive"
    )
    assert "app.modules.not_a_real_module" not in reachable, (
        "detector matches a module that does not exist"
    )
