"""Full Railway deployment for Sales OS — Redis, API, Workers, n8n.

Works with TEAM-SCOPED API tokens (never queries `me`).

    .venv/bin/python scripts/deploy_railway.py --token <TOKEN> [--project sales-os]

Creates (idempotent-ish: reuses project by name):
  - project sales-os
  - service redis  (redis:7-alpine, requirepass, AOF)
  - service api    (Dockerfile infra/Dockerfile.backend, runs migrations first)
  - service workers (same image; outbox relay + pools)
  - service n8n    (n8nio/n8n)
  - public domains for api + n8n

Code uploads happen separately via the Railway CLI (`railway up`) — this script
prints the exact commands.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

import httpx

GRAPHQL = "https://backboard.railway.app/graphql/v2"


class Railway:
    def __init__(self, token: str) -> None:
        self.http = httpx.Client(
            base_url=GRAPHQL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )

    def gql(self, query: str, variables: dict | None = None) -> dict:
        response = self.http.post("/", json={"query": query, "variables": variables or {}})
        data = response.json()
        if data.get("errors"):
            raise SystemExit(f"railway error: {json.dumps(data['errors'])[:400]}")
        return data["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--project", default="sales-os")
    parser.add_argument("--skip-n8n", action="store_true")
    parser.add_argument("--env-file", default=None, help=".env with Supabase DSNs + JWT_SECRET")
    args = parser.parse_args()

    r = Railway(args.token)
    redis_password = secrets.token_urlsafe(16)
    jwt_secret = secrets.token_hex(32)

    # ---------- project (reuse by name if present) ----------
    projects = r.gql("query { projects { edges { node { id name } } } }")["projects"]["edges"]
    existing = next((e["node"] for e in projects if e["node"]["name"] == args.project), None)
    if existing:
        project_id = existing["id"]
        print(f"project reused: {args.project} ({project_id})")
    else:
        project_id = r.gql(
            "mutation($name: String!) { projectCreate(input: { name: $name }) { id } }",
            {"name": args.project},
        )["projectCreate"]["id"]
        print(f"project created: {args.project} ({project_id})")

    environment = r.gql(
        "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } } }",
        {"id": project_id},
    )["project"]["environments"]["edges"][0]["node"]
    env_id = environment["id"]
    print(f"environment: {environment['name']} ({env_id})")

    def find_service(name: str) -> str | None:
        nodes = r.gql(
            "query($id: String!) { project(id: $id) { services { edges { node { id name } } } } }",
            {"id": project_id},
        )["project"]["services"]["edges"]
        return next((e["node"]["id"] for e in nodes if e["node"]["name"] == name), None)

    def create_service(name: str, image: str | None = None) -> str:
        source = {"image": image} if image else None
        input: dict = {"projectId": project_id, "name": name}
        if source:
            input["source"] = source
        return r.gql(
            "mutation($input: ServiceCreateInput!) { serviceCreate(input: $input) { id } }",
            {"input": input},
        )["serviceCreate"]["id"]

    def set_variables(service_id: str, envs: dict[str, str]) -> None:
        r.gql(
            "mutation($projectId: String!, $environmentId: String!, $serviceId: String, "
            "$envs: EnvironmentVariables!) { variableCollectionUpsert(input: { "
            "projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId, "
            "replace: true, variables: $envs }) }",
            {
                "projectId": project_id,
                "environmentId": env_id,
                "serviceId": service_id,
                "envs": envs,
            },
        )

    def instance_update(service_id: str, input: dict) -> None:
        r.gql(
            "mutation($serviceId: String!, $environmentId: String!, "
            "$input: ServiceInstanceUpdateInput!) { serviceInstanceUpdate("
            "serviceId: $serviceId, environmentId: $environmentId, input: $input) }",
            {"serviceId": service_id, "environmentId": env_id, "input": input},
        )

    def domain(service_id: str, target_port: int) -> str:
        result = r.gql(
            "mutation($input: ServiceDomainCreateInput!) { "
            "serviceDomainCreate(input: $input) { domain } }",
            {
                "input": {
                    "serviceId": service_id,
                    "environmentId": env_id,
                    "targetPort": target_port,
                }
            },
        )["serviceDomainCreate"]
        return result["domain"]

    # ---------- redis ----------
    redis_id = find_service("redis") or create_service("redis", "redis:7-alpine")
    set_variables(
        redis_id,
        {
            "REDIS_PASSWORD": redis_password,
            "REDIS_URL": f"redis://:{redis_password}@redis.railway.internal:6379/0",
        },
    )
    instance_update(
        redis_id,
        {"startCommand": "sh -c 'redis-server --requirepass \"$REDIS_PASSWORD\" --appendonly yes'"},
    )
    print(f"redis service ready ({redis_id})")

    # ---------- shared env ----------
    # Secrets arrive via Railway env vars; Supabase values are pasted from .env
    # by the caller (see --env-file below if provided).
    supabase_env: dict[str, str] = {}
    if args.env_file:
        for line in open(args.env_file):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in (
                "DATABASE_URL", "DATABASE_URL_ADMIN", "JWT_SECRET",
                "DATABASE_URL_APP", "DATABASE_URL_APP_ADMIN",
            ):
                supabase_env[key] = value
    if "DATABASE_URL" not in supabase_env:
        raise SystemExit("--env-file must provide DATABASE_URL (Supabase app DSN)")

    common_env = {
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "JWT_SECRET": supabase_env.get("JWT_SECRET", jwt_secret),
        "CORS_ORIGINS": "*",
        "REDIS_URL": "${{redis.REDIS_URL}}",
        **{k: v for k, v in supabase_env.items() if k != "JWT_SECRET"},
    }

    # ---------- api ----------
    print("step: api service...")
    api_id = find_service("api") or create_service("api")
    print("step: api variables...")
    set_variables(
        api_id,
        {
            **common_env,
            "DATABASE_URL_ADMIN": supabase_env.get("DATABASE_URL_ADMIN", ""),
            "RAILWAY_RUN_ID": "",
        },
    )
    print("step: api instance update...")
    instance_update(
        api_id,
        {
            "startCommand": "sh -c 'uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2'",
            "preDeployCommand": "alembic upgrade head",
            "dockerfilePath": "infra/Dockerfile.backend",
            "healthcheckPath": "/healthz",
        },
    )
    print("step: api domain...")
    api_domain = domain(api_id, 8000)
    print(f"api service ready → https://{api_domain}")

    # ---------- workers ----------
    workers_id = find_service("workers") or create_service("workers")
    set_variables(workers_id, common_env)
    instance_update(
        workers_id,
        {"startCommand": "python -m app.workers.run", "dockerfilePath": "infra/Dockerfile.backend"},
    )
    print(f"workers service ready ({workers_id})")

    # ---------- n8n ----------
    n8n_url = ""
    if not args.skip_n8n:
        n8n_id = find_service("n8n") or create_service("n8n", "n8nio/n8n:latest")
        n8n_password = secrets.token_urlsafe(10)
        set_variables(
            n8n_id,
            {
                "N8N_BASIC_AUTH_ACTIVE": "true",
                "N8N_BASIC_AUTH_USER": "salesos",
                "N8N_BASIC_AUTH_PASSWORD": n8n_password,
                "N8N_ENCRYPTION_KEY": secrets.token_hex(16),
                "GENERIC_TIMEZONE": "Africa/Cairo",
            },
        )
        n8n_url = domain(n8n_id, 5678)
        print(f"n8n ready → https://{n8n_url}  (user=salesos password={n8n_password})")

    print("\n=== NEXT: upload code with the Railway CLI ===")
    print("  npm i -g @railway/cli")
    print("  export RAILWAY_TOKEN=<token>")
    print(f"  railway link -p {project_id} -e {env_id}")
    print("  railway up --service api     # from repo root (uses infra/Dockerfile.backend)")
    print("  railway up --service workers # same upload, second service")
    print("\nthen set on Vercel: NEXT_PUBLIC_API_URL=https://" + api_domain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
