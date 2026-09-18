"""Deploy n8n to Railway via the Management GraphQL API.

Run when a VALID Railway API token is available (Account Settings → API Tokens):

    .venv/bin/python scripts/deploy_n8n.py --token <TOKEN>

Creates: project "sales-os" → service "n8n" (docker image n8nio/n8n:latest)
→ env vars → public domain. Prints the webhook base URL to wire into the
core's integrations.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time

import httpx

GRAPHQL = "https://backboard.railway.app/graphql/v2"


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    response = httpx.post(
        GRAPHQL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    data = response.json()
    if data.get("errors"):
        raise SystemExit(f"railway api error: {data['errors']}")
    return data["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--project", default="sales-os")
    args = parser.parse_args()

    token = args.token
    me = gql(token, "query { me { id name } }")["me"]
    print(f"authenticated as: {me['name']} ({me['id']})")

    project = gql(
        token,
        "mutation($name: String!) { projectCreate(input: { name: $name }) { id } }",
        {"name": args.project},
    )["projectCreate"]
    print(f"project: {project['id']}")

    service = gql(
        token,
        "mutation($projectId: String!, $name: String!, $image: String!) { "
        "serviceCreate(input: { projectId: $projectId, name: $name, "
        "source: { image: $image } }) { id } }",
        {"projectId": project["id"], "name": "n8n", "image": "n8nio/n8n:latest"},
    )["serviceCreate"]
    print(f"service: {service['id']}")

    encryption_key = secrets.token_hex(16)
    basic_password = secrets.token_urlsafe(12)
    envs = {
        "N8N_BASIC_AUTH_ACTIVE": "true",
        "N8N_BASIC_AUTH_USER": "salesos",
        "N8N_BASIC_AUTH_PASSWORD": basic_password,
        "N8N_ENCRYPTION_KEY": encryption_key,
        "N8N_HOST": "n8n.up.railway.app",
        "N8N_PROTOCOL": "https",
        "WEBHOOK_URL": "https://n8n.up.railway.app/",
        "GENERIC_TIMEZONE": "Africa/Cairo",
    }
    gql(
        token,
        "mutation($serviceId: String!, $envs: [VariableInput!]!) { "
        "variableCollectionUpsert(input: { serviceId: $serviceId, replace: true, "
        "variables: $envs }) }",
        {
            "serviceId": service["id"],
            "envs": [{"name": k, "value": v} for k, v in envs.items()],
        },
    )

    domain = gql(
        token,
        "mutation($serviceId: String!, $env: String!) { "
        "serviceDomainCreate(input: { serviceId: $serviceId, environmentId: $env, "
        "domain: null, generateDomain: true }) { id domain } }",
        {"serviceId": service["id"], "env": service["id"]},
    )
    print(json.dumps(domain, indent=2))

    print("\nn8n login: user=salesos password=<see below>")
    print(f"N8N_BASIC_AUTH_PASSWORD={basic_password}")
    print(f"N8N_ENCRYPTION_KEY={encryption_key}")
    print("\nImport infra/n8n/*.workflow.json and set env:")
    print("  SALES_OS_CORE_URL=<your core api url>")
    print("  SALES_OS_SERVICE_TOKEN=<internal service token>")
    print("  WHATSAPP_APP_SECRET / WHATSAPP_ACCESS_TOKEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
