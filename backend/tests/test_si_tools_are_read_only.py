"""The owner assistant READS. It never writes, sends or approves anything.

This is the contract behind "an assistant for the shop owner, read only": no ``si_*`` tool may be
able to change the shop. It is enforced by scanning, not by trusting each author:

* the SQL a handler runs may not contain a write statement;
* a handler may not touch the session's write API (add, delete, merge, flush, commit, ...);
* a tool may not be registered above LOW risk, because HIGH risk means "mutates business state";
* no ``si_*`` tool may import a service from another module (those are where writes live), which
  also keeps the cross-module import guard from growing.

A new tool that breaks one of these fails here, with its name, before it can ship.
"""

from __future__ import annotations

import functools
import inspect
import re
import textwrap

import pytest

import app.modules.ai.agents.sales_intelligence.tools as si
from app.modules.ai.tools import TOOLS

si.register_si_tools()

WRITE_SQL = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE|DROP\s+\w+|"
    r"ALTER\s+\w+|CREATE\s+(TABLE|INDEX|FUNCTION|POLICY|ROLE)|GRANT\s|REVOKE\s)",
    re.IGNORECASE,
)
WRITE_API = re.compile(
    r"\b(session|db|ctx\.session)\.(add|add_all|delete|merge|flush|commit|rollback|refresh|"
    r"execute_many|bulk_save_objects|bulk_insert_mappings)\s*\("
)
SERVICE_IMPORT = re.compile(r"from\s+app\.modules\.(?!ai\b|analytics\b)\w+[\w.]*\s+import")


def _si_tools():
    return sorted(n for n in TOOLS if n.startswith("si_"))


def _unwrap(fn):
    """The author's function, not the wrapper that decorates it."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    if isinstance(fn, functools.partial):
        fn = fn.func
    return fn


def _source_of(name: str) -> str:
    handler = _unwrap(TOOLS[name].handler)
    src = textwrap.dedent(inspect.getsource(handler))
    # the SQL constants a handler reads live at module level, so scan those it names
    extra = []
    for const in re.findall(r"\b(_[A-Z][A-Z0-9_]*SQL\w*)\b", src):
        value = getattr(si, const, None)
        if isinstance(value, str):
            extra.append(value)
    return src + "\n" + "\n".join(extra)


def test_there_are_si_tools_to_scan():
    assert len(_si_tools()) >= 14


@pytest.mark.parametrize("name", _si_tools())
def test_no_si_tool_runs_a_write_statement(name):
    hit = WRITE_SQL.search(_source_of(name))
    assert hit is None, f"{name} contains a write statement: {hit.group(0)!r}"


@pytest.mark.parametrize("name", _si_tools())
def test_no_si_tool_touches_the_session_write_api(name):
    hit = WRITE_API.search(_source_of(name))
    assert hit is None, f"{name} calls the session write API: {hit.group(0)!r}"


@pytest.mark.parametrize("name", _si_tools())
def test_no_si_tool_is_above_low_risk(name):
    assert TOOLS[name].risk_level == "LOW", f"{name} is {TOOLS[name].risk_level}, not LOW"


def test_no_si_tool_imports_a_service_from_another_module():
    offenders = {}
    for name in _si_tools():
        hit = SERVICE_IMPORT.search(_source_of(name))
        if hit:
            offenders[name] = hit.group(0)
    assert not offenders, f"tools import write-capable modules: {offenders}"


# --- the scanner itself must catch what it claims to ---------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "await session.execute(text('INSERT INTO orders (id) VALUES (1)'))",
        "await session.execute(text('update orders set status = 1'))",
        "await session.execute(text('DELETE FROM customers'))",
        "await session.execute(text('TRUNCATE products'))",
        "await session.execute(text('DROP TABLE orders'))",
    ],
)
def test_the_sql_scanner_catches_a_write(snippet):
    assert WRITE_SQL.search(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "session.add(row)",
        "await session.delete(row)",
        "await session.commit()",
        "await session.flush()",
        "db.merge(row)",
    ],
)
def test_the_api_scanner_catches_a_write(snippet):
    assert WRITE_API.search(snippet)


def test_the_scanners_do_not_flag_an_ordinary_read():
    read = "rows = (await session.execute(_sql('SELECT updated_at FROM orders'))).all()"
    assert not WRITE_SQL.search(read)
    assert not WRITE_API.search(read)
    # a column called updated_at / a word like "created" is not a write
    assert not WRITE_SQL.search("SELECT created_at, updated_at, deleted_at FROM orders")
