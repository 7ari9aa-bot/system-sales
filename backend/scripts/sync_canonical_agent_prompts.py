"""Reconcile canonical agents' system_prompt with its definition, then publish.

WHY THIS EXISTS
---------------
`agents.system_prompt` is written in exactly ONE place: `core/provisioning.py`,
when the agent ROW IS CREATED. Nothing re-reads the definition afterwards —
`provision_canonical_agents` finds an existing agent and only re-syncs its TOOLS.

So a prompt fix in `agents/customer/definition.py` never reaches the agent rows
that already exist, and `POST /ai/agents/{id}/publish` snapshots the ROW — a new
version would faithfully carry the OLD text. Editing the file and publishing are
both necessary, and neither is sufficient. That is the whole reason the customer
agent kept shipping instructions to "complete the purchase" after the tools had
already been trimmed.

WHAT IT DOES
------------
1. reads every canonical agent row (kinds whose definition sets `is_canonical`),
2. compares its `system_prompt` with the definition's current text,
3. reports each divergence — or applies it with `--apply`,
4. with `--publish`, snapshots the corrected row into a new immutable version and
   lets the publish path pin a stable deployment when none exists.

Deliberately NOT automatic: a store may have edited its prompt on purpose through
the API. Silently overwriting that inside a background provisioning pass would be
a worse bug than the one this fixes, so the reconcile is an explicit, auditable
command with a dry run by default.

Usage (from backend/):
    .venv/Scripts/python scripts/sync_canonical_agent_prompts.py            # dry run
    .venv/Scripts/python scripts/sync_canonical_agent_prompts.py --apply
    .venv/Scripts/python scripts/sync_canonical_agent_prompts.py --apply --publish
    # production needs the explicit flag (the guard mirrors seed_demo.py):
    .venv/Scripts/python scripts/sync_canonical_agent_prompts.py --apply --publish --allow-remote
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BACKEND_ROOT))

from _bootstrap import load_settings  # noqa: E402

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def prompt_digest(text: str | None) -> str:
    """A short, stable fingerprint so a report line stays readable."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def first_differing_line(old: str | None, new: str | None) -> str:
    """The first line that differs, so a report shows WHAT changed, not just that."""
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    for index in range(max(len(old_lines), len(new_lines))):
        before = old_lines[index] if index < len(old_lines) else "<absent>"
        after = new_lines[index] if index < len(new_lines) else "<absent>"
        if before != after:
            return f"line {index + 1}: {before.strip()[:60]!r} -> {after.strip()[:60]!r}"
    return "identical"


def canonical_definitions() -> dict[str, object]:
    """Every registered definition that declares itself canonical."""
    from app.modules.ai.core.registry import AgentRegistry, discover_agents

    discover_agents()
    return {
        definition.kind: definition
        for definition in AgentRegistry.get_all()
        if (definition.provisioning_policy or {}).get("is_canonical")
    }


def _refuse_remote(host: str) -> str:
    return (
        f"refusing to reconcile {host!r}: it is not a local database.\n"
        "This rewrites agents.system_prompt for every tenant in the database and,\n"
        "with --publish, mints immutable versions. Re-run with --allow-remote if\n"
        "that is what you mean to do."
    )


async def reconcile(*, apply: bool, publish: bool, only_kind: str | None) -> int:
    from sqlalchemy import select
    from sqlalchemy import text as sa_text

    from app.core.db import bind_tenant, get_sessionmaker
    from app.modules.ai.models import Agent
    from app.modules.ai.versions import AIAgentVersionService

    definitions = canonical_definitions()
    kinds = [only_kind] if only_kind else sorted(definitions)
    unknown = [kind for kind in kinds if kind not in definitions]
    if unknown:
        raise SystemExit(f"not a canonical kind: {', '.join(unknown)}")

    changed = 0
    scanned = 0
    published = 0
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        tenant_rows = (await session.execute(sa_text("SELECT id FROM tenants"))).all()
        for (tenant_id,) in tenant_rows:
            await bind_tenant(session, tenant_id)
            agents = (
                (await session.execute(select(Agent).where(Agent.kind.in_(kinds)))).scalars().all()
            )
            for agent in agents:
                scanned += 1
                wanted = definitions[agent.kind].system_prompt_template
                if agent.system_prompt == wanted:
                    continue
                changed += 1
                print(
                    f"{tenant_id} {agent.kind}: {prompt_digest(agent.system_prompt)} -> "
                    f"{prompt_digest(wanted)} | {first_differing_line(agent.system_prompt, wanted)}"
                )
                if not apply:
                    continue
                agent.system_prompt = wanted
                await session.flush()
                if publish:
                    version = await AIAgentVersionService.publish(session, tenant_id, agent.id)
                    published += 1
                    print(f"    published version {version.version} ({version.id})")
            await session.flush()
        if apply:
            await session.commit()
        else:
            await session.rollback()

    verb = "updated" if apply else "would update"
    print(f"\nscanned {scanned} canonical agent rows; {verb} {changed}")
    if publish:
        print(f"published {published} new versions")
    if changed and not apply:
        print("dry run — re-run with --apply (and --publish) to write")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface, exposed so a test can prove the safe defaults hold."""
    parser = argparse.ArgumentParser(
        description="Reconcile canonical agent prompts with their definitions"
    )
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="after applying, publish a new version and pin a stable deployment",
    )
    parser.add_argument("--only-kind", help="restrict to one agent kind, e.g. customer")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit running against a non-local database",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.publish and not args.apply:
        raise SystemExit(
            "--publish implies --apply: refusing to publish a row that was not updated"
        )

    settings = load_settings(require=("database_url_admin",), script=Path(sys.argv[0]).name)
    host = urlsplit(settings.database_url_admin or "").hostname or ""
    if host not in LOCAL_HOSTS and not args.allow_remote:
        raise SystemExit(_refuse_remote(host))

    print(f"=== reconciling canonical agent prompts against {host} ===")
    raise SystemExit(
        asyncio.run(reconcile(apply=args.apply, publish=args.publish, only_kind=args.only_kind))
    )


if __name__ == "__main__":
    main()
