"""Reconcile canonical agent prompts against a Supabase project THROUGH THE API.

WHY THIS EXISTS
---------------
`scripts/sync_canonical_agent_prompts.py` is the right tool — it runs the app's
own publish path — but it needs a database DSN, and a deployment that only holds
a Supabase MANAGEMENT token has no way to obtain the database password (the API
returns the literal placeholder ``[YOUR-PASSWORD]``). This script uses the
management API's SQL endpoint instead, so the same reconcile is possible with
nothing but that token.

WHAT IT DOES, in ONE statement
------------------------------
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
- One atomic statement: all three writes commit together or not at all.
- An agent whose deployment is mid-canary (``canary_percent > 0``) or not
  ``active`` is SKIPPED and reported — repointing a slot a rollout is writing to
  is the deployment API's job, not this script's.
- An agent whose prompt does NOT contain the known-stale marker is SKIPPED
  unless ``--force``: a store that customised its prompt must not be silently
  overwritten by a background pass.
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

# The phrase the retired prompt used to describe the agent's job. Its presence
# marks a row that is a stale copy of the canonical prompt rather than a
# deliberate edit — this is the only thing distinguishing the two.
STALE_MARKER = "إتمام عمليات الشراء"

_API = "https://api.supabase.com/v1/projects/{ref}/database/query"


def _fail(message: str) -> None:
    raise SystemExit(message)


def new_prompt() -> str:
    """The canonical customer prompt, straight from the definition in this tree."""
    import app.modules.ai.agents.customer.definition as definition

    prompt = definition.CUSTOMER_SYSTEM_PROMPT
    if not prompt.strip():
        _fail("the canonical customer prompt is empty")
    return prompt


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _build_sql(*, marker: str, apply: bool) -> str:
    """One statement. With `apply=False` the writes are replaced by SELECTs."""
    prompt_literal = f"convert_from(decode('{_b64(new_prompt())}','base64'),'UTF8')"
    stale = (
        f"(SELECT id FROM agents WHERE kind='customer' "
        f"AND position({_sq(marker)} in system_prompt) > 0)"
    )
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
     WHERE a.kind='customer'
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
WITH stale AS {stale},
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


def _sq(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


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


def probe(token: str, ref: str) -> dict:
    """Read the current state so every run prints before and after."""
    rows = run(
        ref,
        token,
        "SELECT (SELECT count(*) FROM agents WHERE kind='customer') AS customer_agents, "
        "(SELECT count(*) FROM agents WHERE kind='customer' AND is_active AND "
        f"position({_sq(STALE_MARKER)} in system_prompt) > 0) AS stale_prompts, "
        "(SELECT count(*) FROM agent_deployments WHERE coalesce(canary_percent,0) > 0) "
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
        help=f"include agents whose prompt does not contain {STALE_MARKER!r}",
    )
    parser.add_argument(
        "--token",
        help="Supabase access token (default: $SUPABASE_ACCESS_TOKEN)",
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        _fail("no Supabase access token: set SUPABASE_ACCESS_TOKEN or pass --token")

    marker = STALE_MARKER if not args.force else "%"

    before = probe(token, args.ref)
    print(f"=== {args.ref} ===")
    print(f"customer agents          : {before.get('customer_agents')}")
    print(f"carrying the stale prompt: {before.get('stale_prompts')}")
    print(f"deployments mid-rollout  : {before.get('mid_rollout')}")

    sql = _build_sql(marker=marker, apply=args.apply)
    result = run(args.ref, token, sql)
    payload = result[0] if result else {}

    if args.apply:
        print(f"\nrows updated          : {payload.get('rows_updated')}")
        print(f"versions published    : {payload.get('versions_published')}")
        print(f"deployments repointed : {payload.get('deployments_repointed')}")
        after = probe(token, args.ref)
        print(f"stale prompts left     : {after.get('stale_prompts')}")
        if after.get("stale_prompts"):
            print(
                "\nremaining stale prompts are either customised (re-run with --force) "
                "or belong to an agent whose deployment is mid-rollout"
            )
    else:
        print(f"\nwould update           : {payload.get('would_update')}")
        print(f"skipped (mid-rollout)  : {payload.get('skipped_mid_rollout')}")
        print(f"new prompt digest      : {payload.get('new_prompt_digest')}")
        print("\ndry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
