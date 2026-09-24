"""SQL fragments several modules need and none should re-derive."""

from __future__ import annotations

LIKE_ESCAPE = "\\"


def escape_like(term: str) -> str:
    r"""Make a caller's text safe to embed in a LIKE pattern.

    `%` stands for anything and `_` for any one character, so a term typed into a
    search box widens the search the moment it is bound raw — `100%_off` asks for
    every row. The escape character is a backslash, and a statement that uses this
    must declare it (`escape="\\"` on the ORM side, `ESCAPE '\'` in raw SQL) or the
    backslashes stay literal text and the escaping does nothing.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(fragment: str) -> str:
    """A contains-match whose wildcards belong to us and only to us.

    The single owner of `%…%` in this codebase — `tests/test_like_patterns_are_escaped.py`
    fails the moment a call site spells the wrapping out for itself.
    """
    return f"%{escape_like(fragment)}%"
