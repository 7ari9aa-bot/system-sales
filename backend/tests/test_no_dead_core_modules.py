"""Reachability guard: core modules must be reachable from non-test code.

This repo's dominant failure mode is "complete, unit-tested, imported by
nothing". It has happened at least nine times — ``app/core/circuit_breaker.py``,
``app/core/storage.py``, ``BillingSnapshotService``, the ETag/If-Match surface in
``app/core/idempotency.py``, and the modules listed as dead below. A unit test
that imports a module directly proves nothing about whether the product uses it:
it passes forever against an unused module.

So this guard answers the reachability question mechanically, with an AST scan
rather than a grep guess. A grep for ``tenancy`` returns 8 hits in this repo and
every one is an unrelated test *name* (``test_get_enforces_tenant_scope``), so a
text search cannot answer "is this imported or called". Import statements are
what actually bind a module into the running application, so they are what this
scans.

Two lists, two directions:

- ``WIRED_CORE_MODULES`` — modules the product depends on. Each must have at
  least one non-test importer. This is the regression guard: if a refactor
  orphans one of these, this test goes red instead of shipping dead code.
- ``KNOWN_DEAD_CORE_MODULES`` — modules already known to have zero non-test
  importers, recorded with the reason. Asserting they are *still* dead is what
  proves the detector can actually report "dead": a detector that returns an
  importer for everything would pass the wired half vacuously.

If you wire one of the dead modules, move its entry up to ``WIRED_CORE_MODULES``
— that is the intended signal, not a false failure.

No database, no Redis, no app import: this is pure static analysis of the source
tree, so it runs locally.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

import pytest

# The backend package root: <repo>/backend/tests/test_no_dead_core_modules.py
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Source roots that count as "non-test code". ``migrations/`` and ``scripts/``
# are included because ``app.core.model_registry`` is legitimately consumed only
# at alembic/provisioning time — its importers are migrations/env.py and
# scripts/provision.py, not anything under app/. Excluding them would report a
# wired module as dead.
SOURCE_ROOTS: tuple[str, ...] = ("app", "migrations", "scripts")

# Modules the product actually depends on — each MUST have a non-test importer.
# These are the ones the previous waves wired up; they are the model to follow.
WIRED_CORE_MODULES: tuple[str, ...] = (
    "app.core.circuit_breaker",
    "app.core.config",
    "app.core.consent",
    # M12: customer create/identity-resolution canonicalize through it.
    "app.core.contact_norm",
    "app.core.db",
    "app.core.errors",
    "app.core.events.bus",
    "app.core.events.outbox",
    "app.core.events.schemas",
    "app.core.events.writer",
    "app.core.guardrails",
    "app.core.idempotency",
    "app.core.ids",
    "app.core.lease",
    "app.core.middleware",
    "app.core.model_kit",
    "app.core.model_registry",
    "app.core.net_guard",
    "app.core.observability",
    "app.core.pagination",
    "app.core.ratelimit",
    "app.core.redis",
    "app.core.search",
    # §139: the return process (orders/returns.py) drives this engine, so the
    # orchestrator now has a runtime caller (ADR-052).
    "app.core.saga",
    "app.core.security",
    "app.core.storage",
    # §68/G-06 wave: identity/deps.py now publishes the ambient tenant via
    # set_current_tenant(), and DatabaseSecretStore reads it — wired on purpose.
    "app.core.tenancy",
)

# Modules with ZERO non-test importers today, with the reason. Recorded rather
# than deleted: a deletion is the owner's call, and a wrong deletion is
# unrecoverable. See the triage report for what would wire each one.
KNOWN_DEAD_CORE_MODULES: dict[str, str] = {
    # `app.core.money` is NOT here: it was deleted, not rewired (ADR-053). A
    # minor-unit value object nothing imported, whose shape contradicted the
    # NUMERIC(14,2) every money column actually uses.
    "app.core.partitioning": (
        "Zero non-test importers. §56 partition-maintenance helpers are not "
        "run by any worker or script in the source roots."
    ),
    "app.core.search_indexer": (
        "Zero non-test importers. §45 external-search indexer; search runs "
        "on pgvector via app.core.search directly."
    ),
}


def _module_name_for(path: pathlib.Path) -> str:
    """Dotted module name for a source file, ``__init__.py`` -> its package."""
    parts = list(path.relative_to(BACKEND_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _referenced_names(tree: ast.AST, module: str, is_package: bool) -> set[str]:
    """Every dotted name this file binds via import statements.

    ``import a.b.c`` yields a.b.c (plus prefixes); ``from a.b import c`` yields
    a.b.c and a.b. Both are recorded because either can be the module under
    test: ``from app.core import tenancy`` and ``import app.core.tenancy`` are
    the same dependency written two ways.
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
                # Relative import: resolve against this module's package.
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
    """Non-test Python files under the source roots."""
    for root in SOURCE_ROOTS:
        for path in sorted((BACKEND_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            yield path


def importers_of(module: str) -> set[str]:
    """Non-test modules that import ``module`` (directly or via a re-export)."""
    found: set[str] = set()
    for path in _iter_source_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:  # a blind detector is worse than a red test
            raise AssertionError(f"cannot parse {path}: {exc}") from exc
        owner = _module_name_for(path)
        if owner == module:
            continue
        if module in _referenced_names(tree, owner, path.name == "__init__.py"):
            found.add(owner)
    return found


def _module_file(module: str) -> pathlib.Path | None:
    """The source file backing a dotted module name, if it exists."""
    rel = pathlib.Path(*module.split("."))
    for candidate in (BACKEND_ROOT / rel.with_suffix(".py"), BACKEND_ROOT / rel / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@pytest.mark.parametrize("module", WIRED_CORE_MODULES)
def test_every_wired_core_module_has_a_non_test_importer(module: str) -> None:
    """A wired core module must be imported by non-test code, not just tests."""
    assert _module_file(module) is not None, f"{module} does not exist — fix the list"
    importers = importers_of(module)
    assert importers, (
        f"{module} has no non-test importer — it is dead code. Either wire it "
        f"(something in {SOURCE_ROOTS} must import it) or move it to "
        f"KNOWN_DEAD_CORE_MODULES with the reason."
    )


@pytest.mark.parametrize("module", sorted(KNOWN_DEAD_CORE_MODULES))
def test_known_dead_core_modules_have_no_non_test_importer(module: str) -> None:
    """The detector must report these as dead — this is what makes it non-vacuous.

    If this fails because someone wired the module, that is the guard working:
    move the entry to WIRED_CORE_MODULES (and drop its note).
    """
    assert _module_file(module) is not None, f"{module} does not exist — fix the list"
    importers = importers_of(module)
    assert not importers, (
        f"{module} is listed as dead but is now imported by {sorted(importers)}. "
        f"Move it from KNOWN_DEAD_CORE_MODULES to WIRED_CORE_MODULES."
    )


def test_detector_distinguishes_wired_from_dead() -> None:
    """Proof the detector discriminates, so neither list can pass vacuously.

    A detector that always returned importers would pass the wired test above
    while proving nothing; one that always returned none would pass the dead
    test. Both directions are pinned here, plus a name that cannot exist, so the
    wired/dead split above is known to be a real measurement.
    """
    assert importers_of("app.core.circuit_breaker"), "detector found no importer for a wired module"
    assert importers_of("app.core.partitioning") == set(), (
        "detector found importers for a dead module"
    )
    assert importers_of("app.core.not_a_real_module") == set(), "detector matches anything"
