"""Full Railway deployment for Sales OS — Redis, API, Workers.

Works with TEAM-SCOPED API tokens (never queries `me`).

    .venv/bin/python scripts/deploy_railway.py --token <TOKEN> [--project sales-os]

Creates (idempotent-ish: reuses project by name):
  - project sales-os
  - service redis  (redis:7-alpine, requirepass, AOF)
  - service api    (Dockerfile infra/Dockerfile.backend, runs migrations first)
  - service workers (same image; outbox relay + pools)
  - public domain for api

Code uploads happen separately via the Railway CLI (`railway up`) — this script
prints the exact commands.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

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


def _load_deployment_config(
    env_file: str | None, frontend_origin_override: str | None
) -> tuple[dict[str, str], str, str]:
    """Validate every production prerequisite before provisioning any service."""
    if not env_file:
        raise SystemExit("--env-file is required for a production deployment")

    path = Path(env_file)
    if not path.is_file():
        raise SystemExit("--env-file does not exist")

    deployment_env: dict[str, str] = {}
    allowed = {
        "DATABASE_URL",
        "DATABASE_URL_ADMIN",
        "JWT_SECRET",
        "DATABASE_URL_APP",
        "DATABASE_URL_APP_ADMIN",
        "FRONTEND_PUBLIC_URL",
        "CORS_ORIGINS",
        "RESEND_API_KEY",
        "EMAIL_FROM",
        "EMAIL_DELIVERY_ENABLED",
        "S3_ENDPOINT",
        "S3_REGION",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "S3_SIGNED_URL_TTL_SECONDS",
    }
    with path.open(encoding="utf-8") as env_stream:
        for raw_line in env_stream:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in allowed:
                deployment_env[key.strip()] = value.strip().strip("\"'")

    for key in ("DATABASE_URL", "DATABASE_URL_ADMIN"):
        if not deployment_env.get(key):
            raise SystemExit(f"--env-file must provide {key}; migrations need the owner connection")

    jwt_secret = deployment_env.get("JWT_SECRET", "")
    if len(jwt_secret.encode("utf-8")) < 32:
        raise SystemExit("--env-file must provide a stable JWT_SECRET of at least 32 bytes")

    frontend_url = (
        (deployment_env.get("FRONTEND_PUBLIC_URL") or frontend_origin_override or "")
        .strip()
        .rstrip("/")
    )
    parsed_frontend = urlsplit(frontend_url)
    if (
        parsed_frontend.scheme != "https"
        or not parsed_frontend.netloc
        or parsed_frontend.username is not None
        or parsed_frontend.password is not None
        or parsed_frontend.path
        or parsed_frontend.query
        or parsed_frontend.fragment
    ):
        raise SystemExit(
            "set FRONTEND_PUBLIC_URL or --frontend-origin to the HTTPS frontend origin"
        )

    frontend_origin = f"https://{parsed_frontend.netloc}"
    cors_value = deployment_env.get("CORS_ORIGINS", frontend_origin).strip()
    cors_values = [origin.strip() for origin in cors_value.split(",") if origin.strip()]
    if not cors_values or "*" in cors_values:
        raise SystemExit("CORS_ORIGINS must list explicit browser origins; '*' is unsafe")
    for origin in cors_values:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise SystemExit("every CORS_ORIGINS entry must be an HTTPS origin")

    storage_keys = (
        "S3_ENDPOINT",
        "S3_REGION",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    )
    missing_storage = [key for key in storage_keys if not deployment_env.get(key)]
    if missing_storage:
        raise SystemExit(
            "production requires Supabase Storage configuration; missing "
            + ", ".join(missing_storage)
        )
    storage_endpoint = urlsplit(deployment_env["S3_ENDPOINT"])
    if (
        storage_endpoint.scheme != "https"
        or not storage_endpoint.netloc
        or storage_endpoint.username is not None
        or storage_endpoint.password is not None
        or storage_endpoint.query
        or storage_endpoint.fragment
    ):
        raise SystemExit("S3_ENDPOINT must be an HTTPS S3-compatible endpoint")
    try:
        signed_url_ttl = int(deployment_env.get("S3_SIGNED_URL_TTL_SECONDS", "900"))
    except ValueError as exc:
        raise SystemExit("S3_SIGNED_URL_TTL_SECONDS must be an integer") from exc
    if not 1 <= signed_url_ttl <= 7 * 24 * 60 * 60:
        raise SystemExit("S3_SIGNED_URL_TTL_SECONDS must be between 1 and 604800")

    email_enabled = deployment_env.get("EMAIL_DELIVERY_ENABLED", "").lower() == "true"
    if not email_enabled:
        raise SystemExit("production requires EMAIL_DELIVERY_ENABLED=true before provisioning")
    if not deployment_env.get("RESEND_API_KEY"):
        raise SystemExit("production requires RESEND_API_KEY before provisioning")
    email_from = deployment_env.get("EMAIL_FROM", "")
    if "@" not in email_from or any(char in email_from for char in "\r\n"):
        raise SystemExit("EMAIL_FROM must be a verified single sender address")

    return deployment_env, frontend_url, ",".join(cors_values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--project", default="sales-os")
    parser.add_argument("--env-file", default=None, help=".env with Supabase DSNs + JWT_SECRET")
    parser.add_argument(
        "--frontend-origin",
        default=None,
        help="public HTTPS frontend origin (or set FRONTEND_PUBLIC_URL in --env-file)",
    )
    args = parser.parse_args()

    # Do not create a Railway project, Redis instance, or service until every
    # production setting (including the recovery mailer) is ready.
    supabase_env, frontend_url, cors_origins = _load_deployment_config(
        args.env_file, args.frontend_origin
    )
    r = Railway(args.token)
    redis_password = secrets.token_urlsafe(16)

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
    # Secrets beyond the deployment/bootstrap settings arrive through Railway's
    # shared project variables. These explicit service variables are kept in sync.
    common_env = {
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "JWT_SECRET": supabase_env["JWT_SECRET"],
        "CORS_ORIGINS": cors_origins,
        "FRONTEND_PUBLIC_URL": frontend_url,
        "RESEND_API_KEY": supabase_env.get("RESEND_API_KEY", ""),
        "EMAIL_FROM": supabase_env.get("EMAIL_FROM", ""),
        "EMAIL_DELIVERY_ENABLED": "true",
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

    print("\n=== NEXT: upload code with the Railway CLI ===")
    print("  npm i -g @railway/cli")
    print("  export RAILWAY_TOKEN=<token>")
    print(f"  railway link -p {project_id} -e {env_id}")
    print("  railway up --service api     # from repo root (uses infra/Dockerfile.backend)")
    print("  railway up --service workers # same upload, second service")
    print("\nthen set on Vercel: VITE_API_URL=https://" + api_domain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
