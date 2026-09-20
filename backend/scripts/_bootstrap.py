"""Shared bootstrap for the operational scripts in this directory.

Ops scripts are run by a human who has a database URL, not by the web app, and
they all hit the same two obstacles:

1. They live in `scripts/`, so `backend/` must be on `sys.path`.
2. They load the app's `Settings`, whose validator refuses to start outside
   `local`/`test` without production-grade secrets (review G-05). That is the
   right default for the web app and pure friction for a script that only needs
   a database URL. Because `ENVIRONMENT` defaults to `production`, the raw
   failure reads `JWT_SECRET must be set in environment 'production'` — which
   looks like a bug in the script rather than a missing variable.

Import this FIRST, before any `app.*` import:

    from _bootstrap import load_settings, session_factory

    async def main() -> int:
        settings = load_settings(require=("database_url_admin",))
        async with session_factory()() as session:
            ...

**It does not guess the environment.** A script pointed at production that
silently ran as `local` would defeat every production guard — `seed_demo.py`
refuses to seed demo data into production, for instance — so an unset
`ENVIRONMENT` stays an error. It is just a legible one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if TYPE_CHECKING:  # pragma: no cover — annotations only
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.config import Settings


def load_settings(*, require: tuple[str, ...] = (), script: str | None = None) -> Settings:
    """Load Settings, or exit with instructions a human can act on.

    `require` names the settings this script cannot work without; each must be a
    non-empty string. Checking them here means a script fails with "set
    DATABASE_URL_ADMIN" instead of connecting to a default localhost database
    and reporting an unrelated error.
    """
    from pydantic import ValidationError

    from app.core.config import get_settings

    try:
        settings = get_settings()
    except ValidationError as exc:
        _explain(str(exc), script=script)
        raise SystemExit(2) from None

    missing = [name for name in require if not getattr(settings, name, "")]
    if missing:
        print(f"missing required configuration: {', '.join(missing)}")
        print()
        print("Set them in the environment (or backend/.env) and re-run, e.g.")
        example = " ".join(f"{name.upper()}=..." for name in missing)
        print(f"  ENVIRONMENT={settings.environment} {example}")
        raise SystemExit(2)

    return settings


def session_factory() -> async_sessionmaker[AsyncSession]:
    """The app's session factory, built from the settings `load_settings` returned.

    Call this INSIDE main() — it is what forces the lazily-built engine into
    existence, and therefore what forces the settings to be valid.
    """
    from app.core.db import get_sessionmaker

    return get_sessionmaker()


def _explain(error: str, *, script: str | None) -> None:
    name = script or Path(sys.argv[0]).name
    print(f"cannot load application settings: {error}")
    print()
    print(
        "Ops scripts load the app's Settings, which refuse to run outside\n"
        "local/test without production-grade secrets. State the environment you\n"
        "are operating on explicitly — this script will not guess:"
    )
    print()
    print(f"  ENVIRONMENT=local {name}")
    print(f"  ENVIRONMENT=production {name}   # also needs JWT_SECRET and the prod URLs")
