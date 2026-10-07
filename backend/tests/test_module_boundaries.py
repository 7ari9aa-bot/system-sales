"""Module boundary enforcement (review G-16 / N-03).

The audit measured cross-module imports growing 62 → 75 and found no
import-linter or architectural test, so nothing stopped the next feature from
coupling modules further. There is now a ratchet.

Three rules, in increasing strictness:

1. **No new import CYCLE between modules.** Cycles are counted as strongly
   connected components, and two of them are baselined below; a third, or a
   bigger one, fails. Cycles are the reason this codebase is full of
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
import random

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
# 102 -> 103 on 2026-09-22: the then-active external workflow adapter added a
# token-model edge; the adapter has since been removed, so that edge is gone.
# 103 -> 104 on 2026-09-22, one deliberate edge (wave-1 review B1):
# platform.router.admin_update_tenant_status -> identity.service.
# TenantLifecycleService.transition is the SINGLE writer of lifecycle_state
# + is_active (§48); the review's whole finding was that the admin endpoint
# bypassed it. Any other seam (raw model write, read-model copy) re-opens
# the bug this edge closes. Function-scope import, and platform -> identity
# already exists at module scope (deps/models), so no new cycle forms.
# 104 -> 97 on 2026-09-23: the pay-back wave-3 asked for instead of another
# ceiling raise. Seven edges DELETED, no new dependency invented, nothing moved
# into app.core to hide it:
#   1-2. customers/timeline.py `_orders` / `_payments` read `orders`,
#        `order_payments` and `refunds` with parameter-bound SQL instead of
#        importing `orders.models` — the CUSTOMER 360 projection is a read model
#        and `OrderService._recompute_lifetime_value` is the precedent for
#        reading another domain's rows this way. Takes `customers -> orders` out
#        of the graph entirely.
#   3.   customers/timeline.py `_tasks` likewise for `operations.models.Task`.
#   4.   billing.used_this_period("tenant_users") counts seats with one SQL
#        COUNT over `tenant_users` rather than importing `identity.models`.
#   5.   EntitlementService.can needs one boolean off `tenants`; it selects
#        `is_active` instead of importing `identity.models.Tenant`.
#   6.   identity.bootstrap's subscription probe asks BillingService
#        (has_any_subscription / plan_exists) instead of importing
#        `billing.models` — which-subscription-states-count is billing's own
#        vocabulary, so this is the preferred fix, not a workaround.
#   7.   identity.bootstrap seeds the default calendar and SLA policy with
#        INSERT … SELECT … WHERE NOT EXISTS instead of importing
#        `operations.models`, same as the ai_budget_policies row beside it, and
#        it gains the atomicity that two-step check-then-insert never had.
# Edge 7 is also what broke the blob: see BASELINE_CYCLIC_SCCS.
#
# 97 -> 94 on 2026-09-24. The real count had already drifted to 99: the CSV
# import feature added a 5th `-> platform.service.AuditService` site
# (catalog.router), and the baseline was NOT raised to meet it. Auditing is a
# cross-cutting capability, not another module's contract, so the shared §66
# writer moved to `app.core.audit.write_audit_row` — the same parameter-bound
# INSERT the orders precedent already made with raw SQL. That takes the five
# `conversations/customers/identity/privacy/catalog -> platform` audit edges out
# of the graph at once (99 -> 94) and lets `orders` delegate too, so the INSERT
# exists once. The drop from 97 is the debt the CSV feature owed and this
# refactor pays off — not a ceiling lifted to hide it.
#
# 94 -> 92 on 2026-09-24, the §137 inbox read model. One edge is this change's:
# `conversations/service.py` no longer imports `customers.service`, because the
# inbox list left the write service for `conversations/inbox.py`, which joins
# `customers` with parameter-bound SQL exactly as `customers/timeline.py` joins
# `orders` (edge 1 above). The other was already gone and the ceiling simply
# had not been lowered to meet it. Module-scope service imports stay at 5 — the
# one this deletes is function-scope — and the SCC pair is unchanged, so both
# hard rules hold. `customers -> conversations.inbox` (the 360 now reads the
# same read model instead of calling `list_inbox`) is a re-point of the existing
# `customers -> conversations.service` edge, not a new coupling.
# 99 -> 116 on 2026-10-01: the Sales Intelligence agent (spec §1.2) imports
# the analytics layer's PUBLIC interfaces (contracts, semantic registry,
# compiler, capabilities, evidence, findings, numbers, validators) — the one
# dependency direction the architecture endorses (agents -> analytics; never
# analytics -> agents, never an ORM model across). All 17 new edges are
# ai -> analytics function/module-scope imports in the SI agent module.
# 117 -> 121 on 2026-10-02: the SI analysis persistence (analytics.persistence
# + analytics.models imported by the agent orchestrator and the GET route) —
# the same endorsed ai -> analytics public-interface direction.
# 121 -> 124 on 2026-10-03: the seasonality/customers/fulfillment tools
# (same endorsed ai -> analytics direction) + the channel-routing work.
# 125 -> 127 on 2026-10-04: the §13 deep-analysis route (ai/router.py) adds
# two function-scope edges — analytics.persistence (the pending shell) and
# platform.service (the Job control surface). Same endorsed direction; the
# worker-side handler lives in app/workers, outside this counter's scan.
# 127 -> 131 on 2026-10-04: the POS domain (Commerce Core v1.0 §189) reaches
# the core through its PUBLIC surface only — identity.deps, orders.money,
# inventory.service, orders.service (attribution by counting d85c113 vs the
# commerce-core tree). Adapter -> core services is the endorsed direction.
# 131 -> 135 on 2026-10-06: the Meta OAuth connect flow (customers/meta_oauth)
# mirrors the manual connect's edges from inside the same module — identity.deps
# (TenantContext/permission gate), platform.integration_verifier + platform.models
# (the shared Integration row + credential verification), billing.service
# (EntitlementService channel gate). Same pairs customers/router.py already holds;
# the counter scans statements, so the second holder adds four.
# 135 -> 139 on 2026-10-06: the Website builder surface (modules/website +
# catalog/website_platform) — website -> identity.deps (TenantCtxDep, the gate
# every module holds), website -> identity.models (Tenant/User lookups for the
# platform hand-off, one statement), website -> catalog.models (function-scope
# lazy read of the tenant's own product rows), and catalog -> identity.deps
# (get_db on the platform bridge). Same endorsed directions as the platform
# module's existing reads of identity/catalog.
BASELINE_TOTAL_CROSS_MODULE_IMPORTS = 139
# 101 -> 99 on 2026-09-29: the diagnostics engine (platform/diagnostics.py) had
# module-scope imports of `ai.models.Agent`, `inventory.models` and
# `orders.models` — three edges that re-merged the eleven-module SCC blob the
# wave-3 work had split. The engine now reads `agents`, `inventory_balances`
# and `orders` with parameter-bound SQL (the customers/timeline read-model
# precedent), deleting all three edges: 102 (the drifted real count) -> 99.
# 2026-09-27: +2 for Wave A — decisions and evidence each import
# identity.deps exactly once (the same router edge platform already has).
# The ratchet exists to stop GROWTH INSIDE a module, not to forbid new
# modules from joining the dependency graph they are governed by.
# 94 -> 101 on 2026-09-27: V12 Wave A-D modules (decisions, evidence, authority,
# effects, financial) add 9 new cross-module imports — all legitimate:
#   • decisions/evidence/authority/effects/financial routers -> identity.deps
#   • authority -> decisions (executor+service: DecisionService for lease minting)
# Old-module count SHRANK from 94 to 92 (net -2) via prior read-model work.
# The ratchet tightened on the old side; the new modules bring their 9 edges.
BASELINE_MODULE_SCOPE_SERVICE_IMPORTS = 8
# 5 -> 7 on 2026-09-27: authority/executor.py and authority/service.py each import
# decisions.service at module scope — authority IS decisions' enforcer, this is
# the canonical coupling this architecture endorses (§8: "read through the
# module's service"). No new cycles introduced (authority and decisions form no SCC).

# Cycles are identified by their STRONGLY CONNECTED COMPONENT — the set of
# modules that can each reach each other — not by one path between them.
#
# Why the shape changed on 2026-09-23. This baseline used to list nine cycles
# found by a depth-first walk that stopped at the first route back to a node it
# had already seen. Measured with a complete enumeration (Johnson), the graph at
# `f7b4ef6` did not hold nine cycles: it held thirty-odd, because 11 of the 17
# modules sat in a single strongly connected blob — `ai, billing, catalog,
# conversations, customers, identity, inventory, notifications, operations,
# orders, platform`. The nine entries were whatever that one traversal happened
# to print, so the rule was not "no new cycle" but "no cycle shaped like the
# nine I already wrote down": a NEW edge inside the blob could pass, and DELETING
# an edge — the thing the ratchet exists to encourage — reshuffled the traversal
# and failed the test for an improvement. Wave-4 hit exactly that: dropping the
# `customers -> orders` edge split the blob, and the old test called it nine
# regressions.
#
# An SCC baseline has neither hole. It is monotone under edge deletion by
# construction (deleting an edge can only shrink or split a component), and it
# cannot be walked into by adding an edge between two modules that already reach
# each other — a merge is a bigger component, and a bigger component is the
# failure.
#
# 2026-09-23, measured with Tarjan over the current graph (98 cross-module
# edges). One component, eleven modules: almost the whole commerce side of the
# monolith reaches around itself. That is the honest shape of the debt, and it
# is now the ceiling — a twelfth module entering it, or a second component
# appearing between two modules nobody baselined together, both fail. Splitting
# it is the improvement this rule is waiting for; when an agent's read-model work
# breaks the blob in two, `_cyclic_sccs` reports two smaller components,
# `test_module_cycles_only_get_resolved` goes red on purpose, and the baseline
# comes down with it.
#
# 2026-09-23, later the same day — it split. Deleting the last
# identity -> operations import (edge 7 above) took `identity` out of the commerce
# side's back-reach, so the eleven-module blob is now two components, seven and
# three modules, and `notifications` is out of every cycle. `identity` can still
# only be reasoned about together with `billing` and `platform`; that pair is the
# next thing to pay down, and this is the floor it has to beat.
BASELINE_CYCLIC_SCCS: frozenset[frozenset[str]] = frozenset(
    [
        frozenset(
            {
                "ai",
                "catalog",
                "conversations",
                "customers",
                "inventory",
                "operations",
                "orders",
            }
        ),
        frozenset({"billing", "identity", "platform"}),
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


def _cyclic_sccs() -> set[frozenset[str]]:
    """Every strongly connected component with more than one module in it."""
    graph: dict[str, set[str]] = collections.defaultdict(set)
    for source, target, _kind, _scope in _cross_module_imports():
        graph[source].add(target)
        graph.setdefault(target, set())
    return _sccs_of(graph)


def _sccs_of(graph: dict[str, set[str]]) -> set[frozenset[str]]:
    """Tarjan's algorithm, run over a caller-supplied graph.

    Split out so the detector itself can be tested against a graph whose answer
    is known by hand. Unlike the DFS this replaces, the result does not depend on
    the order modules happen to be visited in, and it is monotone under edge
    deletion — which is what makes it a usable ratchet: the only way for a
    component to get bigger is to add an edge.
    """

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        # Recursion, not an explicit stack: the graph is one node per module
        # (17 today), so depth is bounded by that and the body stays legible.
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph[node]):
            if nxt not in index:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            comp = []
            while True:
                z = stack.pop()
                on_stack.discard(z)
                comp.append(z)
                if z == node:
                    break
            components.append(comp)

    for module in sorted(graph):
        if module not in index:
            visit(module)

    return {
        frozenset(comp)
        for comp in components
        if len(comp) > 1 or comp[0] in graph[comp[0]]
    }


# ------------------------------------------------------------ the rules ---


def test_no_new_module_import_cycles() -> None:
    """No component may be bigger than the baseline, and no new one may appear.

    A merged or grown component means two modules that used to be reasoned about
    separately now cannot be. A brand-new component between two modules nobody
    baselined together is the same failure in miniature.
    """
    current = _cyclic_sccs()
    new = sorted(
        " -> ".join(sorted(c))
        for c in current
        if not any(c <= base for base in BASELINE_CYCLIC_SCCS)
    )
    assert not new, (
        "new import cycle(s) between modules: "
        + "; ".join(new)
        + ". Break it with a function-scope import, a read-model, or an event — "
        "see this file's docstring."
    )


def test_module_cycles_only_get_resolved() -> None:
    """If a component shrank or split, tighten the baseline so it cannot return."""
    current = _cyclic_sccs()
    fixed = sorted(
        " -> ".join(sorted(base))
        for base in BASELINE_CYCLIC_SCCS
        if not any(base <= cur for cur in current)
    )
    if fixed:
        pytest.fail(
            "good news — these cyclic components shrank or split: "
            + "; ".join(fixed)
            + ". Replace them in BASELINE_CYCLIC_SCCS with the smaller "
            "components that remain, to lock the improvement in."
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


def test_audit_writers_no_longer_cost_a_platform_edge() -> None:
    """Auditing moved to ``app.core.audit`` — a migrated module must not re-add it.

    Regression guard for the §66 writer refactor. These files previously imported
    ``platform.service.AuditService`` purely to write one audit row, which cost a
    cross-module edge each. The writer now lives in ``app.core.audit`` (a core
    capability, not another module), so importing ``app.modules.platform`` here at
    all would pay back an edge the ratchet just removed.
    """
    migrated = [
        "privacy/service.py",
        "customers/service.py",
        "conversations/service.py",
        "catalog/router.py",
    ]
    offenders = []
    for rel in migrated:
        tree = ast.parse((MODULES_DIR / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            target = _imported_module(node)
            if target and target.startswith("app.modules.platform"):
                offenders.append(rel)
                break
    assert not offenders, (
        "audit writer(s) still import app.modules.platform: "
        + ", ".join(sorted(set(offenders)))
        + " — write through app.core.audit.write_audit_row instead."
    )


def test_the_parser_actually_sees_the_tree() -> None:
    """Guard against a silent no-op: a broken parser would make every rule pass."""
    found = _cross_module_imports()
    assert len(found) > 20, (
        f"the boundary parser found only {len(found)} cross-module imports — "
        "it is probably broken, which would make every other rule vacuous"
    )
    assert _cyclic_sccs(), "cycle detection returned nothing — the graph walk is broken"


def test_the_cycle_detector_measures_cycles_not_traversal_order() -> None:
    """The detector is the rule, so the detector gets tested.

    Three properties the replaced DFS did not have, each checked on a graph whose
    answer is known by hand:

    * it finds a cycle no matter which module the walk starts from — the old
      detector marked nodes globally `seen` and so reported a different cycle set
      depending on visit order, which is how deleting an edge came to read as
      adding one;
    * it separates the two directions of change: adding an edge merges
      components (a regression this file must fail on), deleting one can only
      shrink or split them (an improvement `_cyclic_sccs` must stay silent on);
    * it does not invent a cycle where the graph is a plain chain.
    """
    chain = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert _sccs_of({k: set(v) for k, v in chain.items()}) == set()

    loop = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
    assert _sccs_of({k: set(v) for k, v in loop.items()}) == {frozenset({"a", "b", "c"})}

    # Two disjoint loops plus a bridge: merging them with one new edge is exactly
    # the regression `test_no_new_module_import_cycles` has to catch.
    # Two disjoint loops. One edge between them is not enough to merge them —
    # that only makes them reachable in sequence — so the bridge here runs both
    # ways, which is what puts every module on a single loop. This is exactly the
    # regression `test_no_new_module_import_cycles` has to catch.
    separate = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}
    before = _sccs_of({k: set(v) for k, v in separate.items()})
    assert before == {frozenset({"a", "b"}), frozenset({"c", "d"})}
    one_way = {k: set(v) for k, v in separate.items()}
    one_way["b"] = {"a", "c"}
    assert _sccs_of(one_way) == before, (
        "a one-way bridge merged two loops that cannot reach each other back"
    )

    merged = {k: set(v) for k, v in separate.items()}
    merged["b"] = {"a", "c"}
    merged["d"] = {"c", "a"}
    assert _sccs_of(merged) == {frozenset({"a", "b", "c", "d"})}, (
        "adding a two-way bridge did not merge the components"
    )

    # And the deletion half: cutting the bridge back returns the two components,
    # so an improvement can never be reported as a new cycle.
    merged["b"] = {"a"}
    merged["d"] = {"c"}
    assert _sccs_of(merged) == before

    # Order-independence, which is the property the DFS lacked. The same graph
    # written in three different key orders must report the same components; the
    # replaced detector kept a global `seen` set, so its answer moved with the
    # visit order and a deleted edge could surface a "new" cycle.
    keys = list(merged)
    for _ in range(8):
        shuffled = {k: set(merged[k]) for k in random.sample(keys, len(keys))}
        assert _sccs_of(shuffled) == before, "the detector's answer moved with key order"
