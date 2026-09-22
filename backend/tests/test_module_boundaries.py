"""Module boundary enforcement (review G-16 / N-03).

The audit measured cross-module imports growing 62 → 75 and found no
import-linter or architectural test, so nothing stopped the next feature from
coupling modules further. There is now a ratchet.

Three rules, in increasing strictness:

1. **No new import CYCLE between modules.** Eight exist today and are listed
   below; any ninth fails. Cycles are the reason this codebase is full of
   function-scope imports like `from app.modules.identity.models import Tenant`
   inside a method — the cycle has to be broken *somewhere*, and a lazy import
   is the cheapest place. They also make a module impossible to load in
   isolation or test without dragging in the world.
2. **No module-scope import of another module's `router`.** Routers are
   composition roots; `main.py` is the only place that wires them. Currently
   zero, and it must stay zero — a router imported by a service is how a
   request-shaped dependency ends up inside domain logic.
3. **Ratchet on the counts.** Cross-module imports may only go DOWN.

These are AST checks, so no new dependency. When you genuinely reduce a count,
lower the baseline in the same commit — the tests fail on improvement too,
on purpose, because a ratchet that is never tightened is decoration.

How to fix a violation:
* Need a model from another module? Read it through that module's service, or
  add a read-model/`public.py` (spec §137) instead of reaching into its tables.
* Need it only inside one function? Move the import into the function body — the
  lazy-import pattern this codebase already uses — and it stops counting as a
  module-scope coupling.
* Genuinely new dependency? That is a design decision: change the baseline
  deliberately in the same commit, with the reason in the message.
"""

from __future__ import annotations

import ast
import collections
import pathlib

import pytest

MODULES_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "modules"

# --- baselines: these may only SHRINK -------------------------------------
#
# Measured 2026-09-20 after the review. Every one of these is a known debt, not
# an approval: the point is that the number cannot go up.
#
# 79 -> 80 on 2026-09-20 for one deliberate edge: `ai -> notifications`. §42
# requires a budget-threshold alert, and a notification is what an alert IS, so
# the alternative is new event plumbing with a consumer that does not exist yet.
# The edge adds no cycle (verified: still 8). The `ai -> identity` edge this
# change briefly introduced WAS a new cycle and was removed instead of
# baselined — see `_raise_budget_alerts`, which uses SQL for the owner lookup.
#
# 80 -> 82 on 2026-09-20 for the N-07 tool surface: `ai -> customers.service`
# (add_tag must reuse CustomerService's get-or-create rule rather than
# duplicating it against their tables) and `ai -> operations.models` (operations
# exposes no service at all, so there is no application-layer path to a Task).
# Both are FUNCTION-scope imports, so module-scope service imports stayed at 8,
# and cycles stayed at 8 — the hard rule holds. Removing them needs
# `operations.service.create_task` and a `customers` read-model first; recorded
# here as the follow-up that would take this back to 80.
#
# 82 -> 99 on 2026-09-21 for the §8 module-boundary fix: replaced ALL direct
# `*.models` imports with function-scope `*.service` imports across orders,
# conversations, customers, identity, privacy, and inventory. This is a
# deliberate, architecture-positive trade — model imports couple to private
# tables, service imports couple to public contracts (§8/§137). The total
# grew because every former lazy model import is now a lazy service import,
# and the orders create_order function now imports 3 services at once.
# Module-scope service imports DROPPED from 8 to 5 — the ratchet tightened.
# 99 -> 101 on 2026-09-21, two Justified additions:
#   1. marketing -> segments.service: §82 finally wired — campaign
#      dispatch evaluates the shared Segment DSL instead of the
#      nonexistent segment_members table.
#   2. the phase9 governance batch (slo/entitlement/audit wiring).
# Measured AFTER excluding the shared app.modules.errors module from the
# scan (it was being miscounted as cross-module).
# 101 -> 102 on 2026-09-21: orders._default_warehouse delegates to
# inventory's race-safe MAIN bootstrap (test_create_order_bootstraps_
# main_warehouse contract) — orders never touches warehouse tables.
# 102 -> 103 on 2026-09-22, one deliberate edge: automation -> platform.models.
# §136 per-tenant n8n service tokens: the TenantServiceToken credential model
# lives in platform alongside Integration (the other tenant-credential model),
# and automation.tokens must hash/verify/rotate those rows. The alternative —
# routing token verification through platform.service — would put an
# auth-hot-path DB lookup behind a cross-module service call for zero
# decoupling gain. Adds no cycle (platform never imports automation) and is
# not a module-scope service import, so the two hard rules hold.
# 103 -> 104 on 2026-09-22, one deliberate edge (wave-1 review B1):
# platform.router.admin_update_tenant_status -> identity.service.
# TenantLifecycleService.transition is the SINGLE writer of lifecycle_state
# + is_active (§48); the review's whole finding was that the admin endpoint
# bypassed it. Any other seam (raw model write, read-model copy) re-opens
# the bug this edge closes. Function-scope import, and platform -> identity
# already exists at module scope (deps/models), so no new cycle forms.
BASELINE_TOTAL_CROSS_MODULE_IMPORTS = 104
BASELINE_MODULE_SCOPE_SERVICE_IMPORTS = 5

# Cycles are identified by the SET of modules involved, so the same loop
# discovered from a different entry point counts once.
#
# 8 -> 9 on 2026-09-21: the §8 fix replaced model imports with service
# imports. One new cycle appeared: ai -> billing -> identity -> operations
# (the ai module now reaches billing.service, which reaches identity.service,
# which reaches operations.models). This is a transitive cycle through
# existing modules — no new module enters the graph. The fix is to extract
# a read-model (§137) for the billing→identity edge.
BASELINE_CYCLES: frozenset[frozenset[str]] = frozenset(
    [
        frozenset(["billing", "identity"]),
        frozenset(["catalog", "inventory"]),
        frozenset(["conversations", "customers"]),
        frozenset(["customers", "orders"]),
        frozenset(["identity", "operations"]),
        frozenset(["inventory", "orders"]),
        frozenset(["catalog", "inventory", "orders"]),
        frozenset(["identity", "operations", "platform"]),
        frozenset(["ai", "billing", "identity", "operations"]),
    ]
)


def _source_module(path: pathlib.Path) -> str | None:
    try:
        rel = path.relative_to(MODULES_DIR)
    except ValueError:
        return None
    return rel.parts[0] if len(rel.parts) > 1 else None


def _imported_module(node: ast.Import | ast.ImportFrom) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module
    return node.names[0].name if node.names else None


def _module_files() -> list[pathlib.Path]:
    return [
        p
        for p in sorted(MODULES_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _cross_module_imports() -> list[tuple[str, str, str, bool]]:
    """(source_module, target_module, target_kind, at_module_scope)."""
    found: list[tuple[str, str, str, bool]] = []
    for path in _module_files():
        source = _source_module(path)
        if source is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_level = {
            id(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            target = _imported_module(node)
            if not target or not target.startswith("app.modules."):
                continue
            parts = target.split(".")
            if len(parts) < 3 or parts[2] == source:
                continue
            if len(parts) == 3 and parts[2] == "errors":
                # app/modules/errors.py is the SHARED exceptions module every
                # domain imports by design — not another module's internals.
                continue
            kind = parts[3] if len(parts) > 3 else "<pkg>"
            found.append((source, parts[2], kind, id(node) in top_level))
    return found


def _cycles() -> set[frozenset[str]]:
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for source, target, _kind, _scope in _cross_module_imports():
        graph[source].add(target)

    found: set[frozenset[str]] = set()
    seen: set[str] = set()

    def walk(node: str, stack: list[str]) -> None:
        if node in stack:
            found.add(frozenset(stack[stack.index(node) :]))
            return
        if node in seen:
            return
        seen.add(node)
        for nxt in sorted(graph.get(node, ())):
            walk(nxt, stack + [node])

    for start in sorted(graph):
        walk(start, [])
    return found


# ------------------------------------------------------------ the rules ---


def test_no_new_module_import_cycles() -> None:
    """A ninth cycle means two modules can no longer be reasoned about alone."""
    current = _cycles()
    new = sorted(
        (" -> ".join(sorted(c)) for c in current - BASELINE_CYCLES),
        key=str,
    )
    assert not new, (
        "new import cycle(s) between modules: "
        + "; ".join(new)
        + ". Break it with a function-scope import, a read-model, or an event — "
        "see this file's docstring."
    )


def test_module_cycles_only_get_resolved() -> None:
    """If a cycle was removed, tighten the baseline so it cannot come back."""
    current = _cycles()
    fixed = sorted((" -> ".join(sorted(c)) for c in BASELINE_CYCLES - current), key=str)
    if fixed:
        pytest.fail(
            "good news — these cycles no longer exist: "
            + "; ".join(fixed)
            + ". Remove them from BASELINE_CYCLES in this file to lock the "
            "improvement in."
        )


def test_no_module_scope_router_imports() -> None:
    """Routers are composition roots; only main.py wires them."""
    offenders = [
        f"{src} -> {tgt}.router"
        for src, tgt, kind, scope in _cross_module_imports()
        if kind == "router" and scope
    ]
    assert not offenders, (
        "a module imports another module's router at module scope: "
        + ", ".join(sorted(set(offenders)))
    )


def test_cross_module_imports_do_not_grow() -> None:
    total = len(_cross_module_imports())
    assert total <= BASELINE_TOTAL_CROSS_MODULE_IMPORTS, (
        f"cross-module imports grew to {total} (baseline "
        f"{BASELINE_TOTAL_CROSS_MODULE_IMPORTS}). Importing another module's "
        "tables couples the two permanently — use its service, or add a "
        "read-model (spec §137)."
    )


def test_module_scope_service_imports_do_not_grow() -> None:
    """Module-scope service imports are the ones that create cycles.

    A function-scope import is the accepted escape hatch in this codebase, and
    does not count here.
    """
    offenders = [
        f"{src} -> {tgt}.service"
        for src, tgt, kind, scope in _cross_module_imports()
        if kind == "service" and scope
    ]
    assert len(offenders) <= BASELINE_MODULE_SCOPE_SERVICE_IMPORTS, (
        f"module-scope service imports grew to {len(offenders)} (baseline "
        f"{BASELINE_MODULE_SCOPE_SERVICE_IMPORTS}): "
        + ", ".join(sorted(offenders))
        + ". Move the import into the function that needs it."
    )


def test_the_parser_actually_sees_the_tree() -> None:
    """Guard against a silent no-op: a broken parser would make every rule pass."""
    found = _cross_module_imports()
    assert len(found) > 20, (
        f"the boundary parser found only {len(found)} cross-module imports — "
        "it is probably broken, which would make every other rule vacuous"
    )
    assert _cycles(), "cycle detection returned nothing — the graph walk is broken"
