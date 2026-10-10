"""Schema-skew guard (P0-4): refuse to serve or consume on a stale schema.

The deploy topology runs migrations ONLY in the api service's pre-deploy,
while the workers service deploys independently and has no pre-deploy (two
concurrent `alembic upgrade head` from both services would race for the
migration lock). A workers deploy that lands before the api's pre-deploy
therefore boots new code against an old schema — this happened on
2026-10-09: workers queried `agent_deployments` before `fe2026100808` had
been applied, and every pool crashed on the missing relation.

The guard makes that state unbootable instead of observable in logs: compare
the code's alembic head with the database's `alembic_version` and refuse to
start when they disagree. There is no environment where running behind is
correct — not even locally, because the developer machine runs the same
`alembic upgrade head` that CI does.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class SchemaSkewError(RuntimeError):
    """Refusal to boot because the database schema does not match the code."""


def code_head() -> str | None:
    """The alembic revision this code tree expects, from the script directory."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return ScriptDirectory.from_config(cfg).get_current_head()


def classify_schema_state(applied: list[str], head: str | None) -> str | None:
    """The skew reason for (applied revisions, code head), or None when aligned.

    Pure decision — pinned by tests/test_schema_guard.py; the async wrapper
    only fetches ``applied`` and raises with this text.
    """
    if head is None:
        return "code tree has no alembic revisions (migrations/ missing or empty)"
    if len(applied) > 1:
        return (
            "alembic_version holds multiple revisions "
            f"({', '.join(sorted(applied))}) — the migration chain forked; "
            "resolve the branch before booting"
        )
    if not applied:
        return (
            "database schema is not initialized (no alembic_version row) — "
            "run `alembic upgrade head` (applied by the api service's pre-deploy)"
        )
    if applied[0] != head:
        return (
            f"database schema is at {applied[0]} but this code expects {head} — "
            "the deploy is skewed (workers can boot ahead of the api's "
            "pre-deploy migrations); run `alembic upgrade head` before serving"
        )
    return None


async def assert_schema_current(engine: AsyncEngine) -> None:
    """Raise SchemaSkewError unless the database is at this code's head."""
    head = code_head()
    async with engine.connect() as conn:
        exists = (
            await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
        ).scalar_one()
        if exists is None:
            applied: list[str] = []
        else:
            applied = list(
                (await conn.execute(text("SELECT version_num FROM alembic_version")))
                .scalars()
                .all()
            )

    reason = classify_schema_state(applied, head)
    if reason is not None:
        logger.critical("schema_guard.refusing_boot: %s", reason)
        raise SchemaSkewError(reason)
