"""Who is asking, as the owner assistant's tools can read it.

A tool is registered with ONE permission, and the runner hides a tool the asker lacks (it is never
offered, so the model cannot be talked into calling it). That is the right gate, but it forces one
tool per permission, and a small agent is easier to use with few tools and a parameter that says
which read to run. So a tool that covers several reads checks the permission of the read it was
asked for, here, at the moment it runs.

The shared runner does not hand a tool the asker's permissions and must not be changed for this, so
the chat turn sets them in a context variable around the run, the same way the progress steps are
carried (``chat.progress``). It fails CLOSED: with no permissions known, nothing that needs one is
allowed. A scheduled job or an older route that sets nothing therefore reads only what needs none.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.errors import ValidationError

_HELD: ContextVar[frozenset[str] | None] = ContextVar("si_asker_permissions", default=None)


def _clean(codes: object) -> frozenset[str] | None:
    """Only a real collection of non-blank strings counts; anything else is "unknown"."""
    if not isinstance(codes, (set, frozenset, list, tuple)):
        return None
    return frozenset(c for c in codes if isinstance(c, str) and c.strip())


@contextmanager
def asking_with(codes: Iterable[str] | None):
    """Within this block, a tool that checks a permission sees ``codes`` as the asker's."""
    token = _HELD.set(_clean(codes))
    try:
        yield
    finally:
        _HELD.reset(token)


def held() -> frozenset[str]:
    """What the asker holds; empty when unknown, so a check can only refuse, never allow."""
    return _HELD.get() or frozenset()


def require(code: str, *, what: str) -> None:
    """Refuse, in words the model can relay, unless the asker holds ``code``."""
    if code not in held():
        raise ValidationError(f"the owner is not allowed to read {what} here")
