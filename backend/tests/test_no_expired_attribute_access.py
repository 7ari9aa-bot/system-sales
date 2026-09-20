"""Guard: never touch an attribute of an object `expire_all()` just detached.

WHY THIS EXISTS. Two tests in `test_invoice_immutability.py` called
`db.expire_all()` and then read `tenant_ctx.tenant_id` / `invoice.id` /
`draft.id`. In an async session, `expire_all()` marks every attribute as expired,
so the next access triggers a LAZY REFRESH — which has no greenlet to run on and
raises `sqlalchemy.exc.MissingGreenlet`.

Those two tests are DB-backed, so they SKIP locally ("no app database URL
configured") and only run on CI. The result: `main` stayed RED for hours across
many commits, and every change stacked on top of it was blocked — while each
agent's own report said "passes locally".

That is a defect in the process, not just in two tests. `docs/AGENT_BRIEF.md`
tells agents to "run the test in both states", which is UNENFORCEABLE for a
DB-backed test without a local Postgres. So the lesson has to be enforced
statically instead. This test is that enforcement: it needs no database, so it
runs on every machine, and it fails on the exact pattern that caused the outage.

THE RULE: bind the scalar you need BEFORE `expire_all()`.

    invoice_id = invoice.id          # <- read while still loaded
    db.expire_all()
    assert reread.id == invoice_id   # <- plain local, no lazy load
"""

from __future__ import annotations

import ast
import pathlib

TESTS_DIR = pathlib.Path(__file__).resolve().parent

#: Bases it is safe to touch after `expire_all()`. The session is not an expired
#: ORM row, and these are module-level helpers rather than bound instances.
SAFE_BASES = frozenset(
    {"db", "session", "self", "cls", "pytest", "text", "select", "sa", "uuid", "Decimal"}
)


def _functions(tree: ast.AST) -> list[ast.AST]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _first_expire_all_line(fn: ast.AST) -> int | None:
    lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "expire_all"
    ]
    return min(lines) if lines else None


def _names_bound_before(fn: ast.AST, line: int) -> set[str]:
    """Every local name and argument bound before `line`, minus the safe bases."""
    names: set[str] = set()
    for arg in [
        *fn.args.posonlyargs,  # type: ignore[attr-defined]
        *fn.args.args,  # type: ignore[attr-defined]
        *fn.args.kwonlyargs,  # type: ignore[attr-defined]
    ]:
        names.add(arg.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and node.lineno < line:
            names.update(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
        elif (
            isinstance(node, ast.AnnAssign)
            and node.lineno < line
            and isinstance(node.target, ast.Name)
        ):
            names.add(node.target.id)
    return names - SAFE_BASES


def test_no_attribute_access_on_an_object_expire_all_detached() -> None:
    offenders: list[str] = []

    for path in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # a broken file is another test's problem
            continue
        for fn in _functions(tree):
            line = _first_expire_all_line(fn)
            if line is None:
                continue
            risky = _names_bound_before(fn, line)
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Attribute)
                    and node.lineno > line
                    and isinstance(node.value, ast.Name)
                    and node.value.id in risky
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno}  {node.value.id}.{node.attr}"
                    )

    assert not offenders, (
        "attribute access AFTER expire_all() on an object that was bound earlier.\n"
        "In an async session this raises MissingGreenlet, and because the test is\n"
        "DB-backed it SKIPS locally — so you will not see it until CI, where it\n"
        "blocks every later commit. Bind the scalar BEFORE expiring:\n"
        "    x_id = x.id        # while still loaded\n"
        "    db.expire_all()\n"
        "    use(x_id)\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )
