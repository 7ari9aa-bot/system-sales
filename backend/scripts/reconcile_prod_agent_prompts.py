"""Reconcile canonical agent prompts against a Supabase project THROUGH THE API.

WHY THIS EXISTS
---------------
``scripts/sync_canonical_agent_prompts.py`` is the right tool — it runs the app's
own publish path — but it needs a database DSN, and a deployment that only holds
a Supabase MANAGEMENT token has no way to obtain the database password (the API
returns the literal placeholder ``[YOUR-PASSWORD]``). This script uses the
management API's SQL endpoint instead, so the same reconcile is possible with
nothing but that token.

KIND-AGNOSTIC BY DESIGN
-----------------------
It iterates every canonical kind in the registry, so a THIRD agent is reconciled
by this tool without an edit — its prompt comes from its own definition. What IS
declared per kind is the STALE MARKER (``STALE_MARKERS``): the phrase a kind's
retired prompt used to describe the agent's job, whose presence marks a row as a
stale copy of the canonical prompt rather than a deliberate store edit. A kind
without a marker is never reconciled without ``--force`` — a prompt that does not
match a known canonical revision is the store's own, and overwriting it silently
would be a worse bug than the drift it fixes.

WHAT IT DOES, in ONE statement per kind
---------------------------------------
1. ``UPDATE agents.system_prompt`` — the row, so the definition and the store agree,
2. ``INSERT INTO agent_versions`` — an immutable snapshot, version = max + 1,
3. ``UPDATE agent_deployments.stable_version_id`` — repoint the stable slot.

Step 3 is not optional: production already has deployment rows (migration
fe2026100818 created them), and ``_ensure_stable_deployment`` is deliberately
creation-only, so a publish alone would mint a version nobody serves. The runtime
pins the STABLE version, not the row.

SAFETY
------
- Dry run by default. The write needs ``--apply``.
- One atomic statement per kind: all three writes commit together or not at all.
- An agent whose deployment is mid-canary (``canary_percent > 0``) or not
  ``active`` is SKIPPED and reported — repointing a slot a rollout is writing to
  is the deployment API's job, not this script's.
- The prompt travels base64-encoded, so no quoting or dialect can corrupt it.

Usage (from backend/):
    export SUPABASE_ACCESS_TOKEN=sbp_...
    .venv/Scripts/python scripts/reconcile_prod_agent_prompts.py --ref <project-ref>
    .venv/Scripts/python scripts/reconcile_prod_agent_prompts.py --ref <ref> --apply
    .venv/Scripts/python scripts/reconcile_prod_agent_prompts.py --ref <ref> --apply --force
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Per kind: the phrase its RETIRED prompt used to describe the agent's job. Its
# presence marks a row that is a stale copy of the canonical prompt rather than a
# deliberate edit — the only thing distinguishing the two. A kind WITHOUT an
# entry is never reconciled without --force.
STALE_MARKERS: dict[str, str] = {
    "customer": "إتمام عمليات الشراء",
}

_API = "https://api.supabase.com/v1/projects/{ref}/database/query"


def _fail(message: str) -> None:
    raise SystemExit(message)


def canonical_definitions() -> dict[str, object]:
    """Every registered definition that declares itself canonical."""
    from app.modules.ai.core.registry import AgentRegistry, discover_agents

    discover_agents()
    return {
        definition.kind: definition
        for definition in AgentRegistry.get_all()
        if (definition.provisioning_policy or {}).get("is_canonical")
    }


def prompt_for(kind: str) -> str:
    """The canonical prompt of `kind`, straight from its definition in this tree."""
    definition = canonical_definitions().get(kind)
    if definition is None:
        _fail(f"{kind} is not a canonical kind")
    prompt = definition.system_prompt_template  # type: ignore[attr-defined]
    if not prompt.strip():
        _fail(f"the canonical {kind} prompt is empty")
    return prompt


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _sq(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _build_sql(*, kind: str, marker: str, prompt: str, apply: bool) -> str:
    """One atomic statement for ONE kind: row, snapshot, stable pointer.

    With ``apply=False`` the writes are replaced by SELECTs that report what
    WOULD change, so a dry run exercises the same eligibility rules.
    """
    prompt_literal = f"convert_from(decode('{_b64(prompt)}','base64'),'UTF8')"
    if apply:
        head = f"""
WITH params AS (SELECT {prompt_literal} AS new_prompt),
target AS (
    SELECT a.id AS agent_id, a.tenant_id, a.model, a.temperature, a.max_output_tokens,
           a.run_limits, v.tool_policy, v.version AS max_version
      FROM agents a
      LEFT JOIN LATERAL (
            SELECT ver.version, ver.tool_policy
              FROM agent_versions ver
             WHERE ver.tenant_id = a.tenant_id AND ver.agent_id = a.id
               AND ver.status='published'
             ORDER BY ver.version DESC
             LIMIT 1
      ) v ON true
     WHERE a.kind = {_sq(kind)}
       AND a.is_active
       AND (position({_sq(marker)} in a.system_prompt) > 0)
       AND NOT EXISTS (
             SELECT 1 FROM agent_deployments d
              WHERE d.tenant_id = a.tenant_id AND d.agent_id = a.id
                AND (coalesce(d.canary_percent,0) > 0 OR d.status <> 'active'))
),
upd AS (
    UPDATE agents a SET system_prompt = p.new_prompt, updated_at = now()
      FROM target t, params p WHERE a.id = t.agent_id
    RETURNING a.id AS agent_id, a.tenant_id, a.model, a.temperature,
              a.max_output_tokens, a.run_limits, t.tool_policy, t.max_version
),
ver AS (
    INSERT INTO agent_versions
        (tenant_id, agent_id, version, system_prompt, model, temperature,
         max_output_tokens, run_limits, tool_policy, status, published_at,
         created_at, updated_at)
    SELECT u.tenant_id, u.agent_id, coalesce(u.max_version,0)+1, p.new_prompt,
           u.model, u.temperature, u.max_output_tokens,
           coalesce(u.run_limits,'{{}}'::jsonb), coalesce(u.tool_policy,'{{}}'::jsonb),
           'published', now(), now(), now()
      FROM upd u, params p
    RETURNING id AS version_id, agent_id, tenant_id, version
),
dep AS (
    UPDATE agent_deployments d SET stable_version_id = ver.version_id, updated_at = now()
      FROM ver
     WHERE d.tenant_id = ver.tenant_id AND d.agent_id = ver.agent_id
       AND coalesce(d.canary_percent,0) = 0 AND d.status = 'active'
       AND d.stable_version_id IS DISTINCT FROM ver.version_id
    RETURNING d.id
)
SELECT (SELECT count(*) FROM upd) AS rows_updated,
       (SELECT count(*) FROM ver) AS versions_published,
       (SELECT count(*) FROM dep) AS deployments_repointed"""
    else:
        head = f"""
WITH stale AS (
    SELECT id FROM agents
     WHERE kind = {_sq(kind)}
       AND is_active
       AND (position({_sq(marker)} in system_prompt) > 0)
),
skipped_canary AS (
    SELECT a.id FROM agents a
     WHERE a.id IN (SELECT id FROM stale)
       AND EXISTS (SELECT 1 FROM agent_deployments d
                    WHERE d.tenant_id = a.tenant_id AND d.agent_id = a.id
                      AND (coalesce(d.canary_percent,0) > 0 OR d.status <> 'active'))
),
eligible AS (SELECT id FROM stale WHERE id NOT IN (SELECT id FROM skipped_canary))
SELECT (SELECT count(*) FROM stale) AS stale_rows,
       (SELECT count(*) FROM skipped_canary) AS skipped_mid_rollout,
       (SELECT count(*) FROM eligible) AS would_update,
       md5({prompt_literal}) AS new_prompt_digest"""
    return head.strip()


def run(ref: str, token: str, sql: str) -> list[dict]:
    request = urllib.request.Request(
        _API.format(ref=ref),
        data=json.dumps({"query": sql}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        _fail(f"Supabase API rejected the query: HTTP {exc.code}\n{exc.read().decode()[:400]}")
    return []


def probe(ref: str, token: str, kind: str) -> dict:
    """Read the current state of ONE kind so every run prints before and after."""
    rows = run(
        ref,
        token,
        "SELECT (SELECT count(*) FROM agents WHERE kind = "
        + _sq(kind)
        + ") AS agents, "
        + "(SELECT count(*) FROM agents WHERE kind = "
        + _sq(kind)
        + " AND is_active AND position("
        + _sq(STALE_MARKERS.get(kind, "\x00"))
        + " in system_prompt) > 0) AS stale_prompts, "
        + "(SELECT count(*) FROM agent_deployments WHERE coalesce(canary_percent,0) > 0) "
        "AS mid_rollout",
    )
    return rows[0] if rows else {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile canonical agent prompts on a Supabase project"
    )
    parser.add_argument("--ref", help="Supabase project ref", required=True)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="reconcile a kind with no known stale marker, and rows that are not "
        "stale canonical copies (a store's own edit)",
    )
    parser.add_argument(
        "--only-kind", help="restrict to one kind, e.g. customer (default: every canonical kind)"
    )
    parser.add_argument(
        "--token",
        help="Supabase access token (default: $SUPABASE_ACCESS_TOKEN)",
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        _fail("no Supabase access token: set SUPABASE_ACCESS_TOKEN or pass --token")

    definitions = canonical_definitions()
    kinds = [args.only_kind] if args.only_kind else sorted(definitions)
    unknown = [kind for kind in kinds if kind not in definitions]
    if unknown:
        _fail(f"not a canonical kind: {', '.join(unknown)}")

    totals = {"rows": 0, "versions": 0, "deployments": 0}
    for kind in kinds:
        marker = STALE_MARKERS.get(kind)
        forced = args.force and marker is None
        if marker is None and not args.force:
            print(f"\n=== {kind}: no stale marker declared — skipped (use --force) ===")
            continue
        if forced:
            marker = "%"
            print(f"\n=== {kind} (--force: every active row is eligible) ===")
        else:
            print(f"\n=== {kind} ===")

        before = probe(args.ref, token, kind)
        print(f"agents                  : {before.get('agents')}")
        print(f"carrying a stale prompt : {before.get('stale_prompts')}")
        print(f"deployments mid-rollout : {before.get('mid_rollout')}")

        sql = _build_sql(kind=kind, marker=marker, prompt=prompt_for(kind), apply=args.apply)
        payload = (run(args.ref, token, sql) or [{}])[0]

        if args.apply:
            rows = payload.get("rows_updated", 0) or 0
            versions = payload.get("versions_published", 0) or 0
            deployments = payload.get("deployments_repointed", 0) or 0
            totals["rows"] += rows
            totals["versions"] += versions
            totals["deployments"] += deployments
            after = probe(args.ref, token, kind)
            print(f"rows updated          : {rows}")
            print(f"versions published    : {versions}")
            print(f"deployments repointed : {deployments}")
            print(f"stale prompts left    : {after.get('stale_prompts')}")
        else:
            print(f"would update           : {payload.get('would_update')}")
            print(f"skipped (mid-rollout)  : {payload.get('skipped_mid_rollout')}")
            print(f"new prompt digest      : {payload.get('new_prompt_digest')}")

    if args.apply:
        print(f"\nTOTAL rows updated: {totals['rows']} | versions: {totals['versions']} "
              f"| deployments: {totals['deployments']}")
    else:
        print("\ndry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
