"""§A7 — a typed LIKE wildcard is data, never a pattern, and one function builds it.

A search box, a command palette and a segment rule all answer the same question:
"does this column contain what the caller typed?" In Postgres that is a `LIKE`
pattern, and a pattern has two metacharacters the caller can type: `%` (anything,
any length) and `_` (any one character). Wrapping the term in `%…%` without
escaping it means a customer searching `100%_off` is silently answered with
*every* product, and a marketer saving a segment rule `source contains %` is
about to send a campaign to the whole tenant.

Three sites did exactly that — the merchant's customer search, global search
(which is raw SQL, so it needed an `ESCAPE` clause in the text as well), and the
segment DSL. `orders` had already solved it with a helper; the helper now lives
in `core/sql.py` where every module may reach it, and the two AST guards at the
bottom keep a fourth site from appearing: no `%`-wrapped pattern is built inline
in `app/`, and no `ilike`/`like` call passes a non-literal term without declaring
its escape character.

DB-free by design: each assertion compiles the statement the code actually built
(or reads the raw SQL text it sent) and inspects the bound parameters, so the
shape is provable on a laptop with no database — `pattern` reaching the driver as
`%50\\%\\_off%` is the whole claim.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

APP_DIR = Path(__file__).resolve().parents[1] / "app"

TERM = "50%_off"
ESCAPED = r"%50\%\_off%"  # what the driver must receive


class _NoRows:
    def all(self) -> list:
        return []

    def first(self):  # noqa: ANN201
        return None

    def scalars(self):  # noqa: ANN201
        return self

    def mappings(self):  # noqa: ANN201
        return self

    def scalar_one(self):  # noqa: ANN201
        return 0

    def scalar_one_or_none(self):  # noqa: ANN201
        return None


class _Capture:
    """Records whatever a call hands the driver, then answers "no rows".

    Both call shapes in this repo are covered: the ORM path passes one
    statement, `text()` SQL passes (statement, params).
    """

    def __init__(self) -> None:
        self.statement = None
        self.params: dict = {}

    async def execute(self, statement, params=None):  # noqa: ANN001, ARG002
        self.statement = statement
        self.params = dict(params or {})
        return _NoRows()

    def rendered(self) -> tuple[str, list[str]]:
        """(SQL text, every string value bound to it)."""
        if self.params:
            return str(self.statement), [v for v in self.params.values() if isinstance(v, str)]
        compiled = self.statement.compile(dialect=postgresql.dialect())
        return str(compiled), [v for v in compiled.params.values() if isinstance(v, str)]


def _ilike_claims(rendered_sql: str, values: list[str]) -> tuple[bool, list[str]]:
    has_escape = "ESCAPE" in rendered_sql.upper()
    patterns = [v for v in values if v.startswith("%") and v.endswith("%") and len(v) > 2]
    return has_escape, patterns


# ---------------------------------------------------------------- site 1: customers


def test_customer_search_escapes_the_term_it_binds() -> None:
    from app.modules.customers.service import CustomerService

    session = _Capture()
    asyncio.run(CustomerService.list_customers(session, uuid.uuid4(), search=TERM, limit=10))
    sql, values = session.rendered()
    has_escape, patterns = _ilike_claims(sql, values)

    assert patterns, "the search built no LIKE pattern at all"
    assert ESCAPED in patterns, f"term bound unescaped: {patterns}"
    assert has_escape, "ILIKE with backslash escapes and no ESCAPE clause matches literals"


# -------------------------------------------------------------------- site 2: search


def test_global_search_escapes_wildcards_and_keeps_an_apostrophe() -> None:
    from app.core.search import PostgresSearch

    session = _Capture()
    asyncio.run(PostgresSearch().search(session, uuid.uuid4(), TERM, limit=5))
    sql, values = session.rendered()
    has_escape, patterns = _ilike_claims(sql, values)

    assert patterns, f"no LIKE param reached the driver: {values}"
    assert ESCAPED in patterns, f"term bound unescaped: {patterns}"
    assert has_escape, f"raw SQL declares no escape character:\n{sql}"

    # The same path doubled every apostrophe before binding. The value is a
    # bound parameter, not SQL text, so `O'Neil` needs no quoting — and once it
    # gets `O''Neil` the merchant searches for a customer who is right there.
    quote_session = _Capture()
    asyncio.run(PostgresSearch().search(quote_session, uuid.uuid4(), "O'Neil", limit=5))
    _, quote_values = quote_session.rendered()
    assert any("O'Neil" in v for v in quote_values), (
        f"apostrophe was mangled before binding: {quote_values}"
    )


# ------------------------------------------------------------------- site 3: segments


def test_segment_contains_escapes_the_stored_value() -> None:
    from app.modules.segments.service import _compile_where

    params: dict = {}
    fragment = _compile_where(
        {"all": [{"field": "source", "op": "contains", "value": TERM}]}, params
    )
    assert "ESCAPE" in fragment.upper(), f"segment SQL has no escape clause: {fragment}"
    assert ESCAPED in params.values(), f"segment value bound unescaped: {params}"


def test_segment_contains_still_accepts_a_value_that_is_not_a_string() -> None:
    """The DSL validates that a condition carries a value, not that the value is
    text — and JSON numbers arrive from the rule builder. Interpolating one into
    a pattern always worked, so escaping it must not turn `contains 5` into a
    500 on the way."""
    from app.modules.segments.service import _compile_where

    params: dict = {}
    _compile_where({"all": [{"field": "source", "op": "contains", "value": 5}]}, params)
    assert params["p0"] == "%5%"


# ------------------------------------------------------------------ site 4: orders


def test_order_number_search_still_escapes_after_the_helper_moved() -> None:
    """`orders` was the site that already had this right; the helper moved out of
    its module, so this pins that the call kept the escaping and the escape
    declaration. It passes on arrival by design — it is the tripwire, not the
    proof, and unlike the three sites above it was never red."""
    from app.modules.orders.service import OrderService

    session = _Capture()
    asyncio.run(OrderService.list_orders(session, uuid.uuid4(), number=TERM, limit=5))
    sql, values = session.rendered()
    _, patterns = _ilike_claims(sql, values)

    assert ESCAPED in patterns, f"term bound unescaped: {patterns}"
    assert "ESCAPE" in sql.upper(), f"ILIKE declares no escape character:\n{sql}"


# --------------------------------------------------------------- the two AST guards


def _offending_pattern_strings(tree: ast.AST) -> list[str]:
    """`f"…%{x}%…"` — a LIKE pattern assembled at the call site.

    Legal exactly once, inside the helper that owns the rule; anywhere else it is
    a wildcard that escapes whoever typed the term.

    The shape is a contains-wrap: the literal text opens with `%` before the
    first interpolation and closes with `%` after the last. Prose that merely
    mentions a percentage (`f"used {ratio}% of the cap"`) is not that shape and
    must not be flagged, or the guard trains people to ignore it.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or len(node.values) < 3:
            continue
        head, tail = node.values[0], node.values[-1]
        opens = isinstance(head, ast.Constant) and str(head.value).endswith("%")
        closes = isinstance(tail, ast.Constant) and str(tail.value).startswith("%")
        if opens and closes:
            hits.append(f"line {node.lineno}: f-string builds a LIKE pattern")
    return hits


def _offending_ilike_calls(tree: ast.AST) -> list[str]:
    """`.ilike(term)` / `.like(term)` with a computed term and no `escape=`.

    A literal pattern (`like("audio/%")`) is the developer's own text and stays
    allowed; anything else came from a caller.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"ilike", "like"} or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant):
            continue
        if any(kw.arg == "escape" for kw in node.keywords):
            continue
        hits.append(f"line {node.lineno}: .{node.func.attr}() without escape=")
    return hits


def test_like_patterns_are_only_built_in_one_place() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "sql.py" and path.parent.name == "core":
            continue
        found = _offending_pattern_strings(ast.parse(path.read_text(encoding="utf-8")))
        offenders.extend(f"{path.relative_to(APP_DIR.parent)}: {o}" for o in found)
    assert not offenders, (
        "LIKE patterns must come from core/sql.py::like_pattern, not an inline "
        "f-string (a typed % or _ would widen the search):\n" + "\n".join(offenders)
    )


def test_every_computed_like_pattern_declares_its_escape() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        found = _offending_ilike_calls(ast.parse(path.read_text(encoding="utf-8")))
        offenders.extend(f"{path.relative_to(APP_DIR.parent)}: {o}" for o in found)
    assert not offenders, (
        "an escaped pattern does nothing unless the statement declares the escape "
        "character; add escape='\\\\':\n" + "\n".join(offenders)
    )


def test_the_guards_fire_on_the_shapes_they_claim_to_catch() -> None:
    """A guard that cannot fail is decoration — so the detectors run on source
    that has the defect, and on source that does not, in the same test."""
    bad = ast.parse(
        "def f(q):\n"
        "    p = f'%{q}%'\n"
        "    return p\n"
        "def g(col, q):\n"
        "    return col.ilike(f'%{q}%')\n"
    )
    assert _offending_pattern_strings(bad) == [
        "line 2: f-string builds a LIKE pattern",
        "line 5: f-string builds a LIKE pattern",
    ]
    assert _offending_ilike_calls(bad) == ["line 5: .ilike() without escape="]

    # Precision: a budget notice quotes a real percentage and must stay silent.
    prose = ast.parse(
        "def notice(ratio, cap):\n    return f'used {ratio:.0f}% of the monthly cap ({cap})'\n"
    )
    assert _offending_pattern_strings(prose) == []

    good = ast.parse(
        "from app.core.sql import like_pattern\n"
        "def g(col, q):\n"
        "    return col.ilike(like_pattern(q), escape='\\\\')\n"
        "def h(col):\n"
        "    return col.like('audio/%')\n"
    )
    assert _offending_pattern_strings(good) == []
    assert _offending_ilike_calls(good) == []


def test_like_pattern_helper_is_the_single_owner() -> None:
    from app.core.sql import like_pattern

    assert like_pattern(TERM) == ESCAPED
    assert like_pattern(r"a\b") == r"%a\\b%"
    assert like_pattern("") == "%%"
    with pytest.raises((AttributeError, TypeError)):
        like_pattern(None)  # type: ignore[arg-type]
