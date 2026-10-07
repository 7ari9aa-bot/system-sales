"""§125 / ADR-060: the tenant boundary is never a URL parameter — anywhere.

The rule already existed as a pinned test for ONE router
(`tests/test_automation_routes.py:206`: "tenancy is the request context's,
never a parameter") and SEC-1 found the hole the pin left:
`POST /auth/switch-tenant` accepted `tenant_id` as a query parameter — a
credential-shaped value in a field every hop logs, caches and echoes.

This guard generalizes the rule over the WHOLE published graph, so the next
route that accepts tenancy from the query string fails CI instead of waiting
for the next audit. Resource filters (`?customer_id=`, `?status=`) are not the
tenant boundary and stay legal; `tenant_id` — and the `organization_id` alias
external specs keep inventing for the same concept — are not.
"""

from __future__ import annotations

import pytest

from app.main import create_app

TENANT_PARAMETER_NAMES = {"tenant_id", "organization_id", "org_id"}


@pytest.fixture(scope="module")
def operations() -> dict:
    # The schema builds synchronously; a TestClient here would open and close
    # an event loop inside a pytest-asyncio session and poison the async tests
    # that share this worker (CI: "RuntimeError: Event loop is closed").
    return create_app().openapi()["paths"]


def test_no_operation_accepts_the_tenant_boundary_as_a_query_parameter(operations):
    offenders = []

    for path, path_item in operations.items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "query":
                    continue
                if parameter.get("name") in TENANT_PARAMETER_NAMES:
                    offenders.append(f"{method.upper()} {path}: ?{parameter['name']}=")

    assert not offenders, (
        "the tenant boundary leaked into the query string; a query parameter is "
        "logged by every proxy and echoed by every client — resolve tenancy from "
        "the authenticated context (or a typed body for the deliberate switch "
        "flow), then regenerate desktop/openapi_lock.json:\n  " + "\n  ".join(offenders)
    )


def test_switch_tenant_carries_the_target_tenant_in_the_typed_body(operations):
    """The one legitimate tenant choice left: switching, from the body only."""

    operation = operations["/api/v1/auth/switch-tenant"]["post"]

    query_names = {p.get("name") for p in operation.get("parameters", []) if p.get("in") == "query"}
    assert not (query_names & TENANT_PARAMETER_NAMES), query_names

    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema_name = body.get("schema", {}).get("$ref", "").rsplit("/", 1)[-1]
    assert schema_name == "SwitchTenantRequest", (
        f"switch-tenant must take the target tenant from a typed "
        f"SwitchTenantRequest body, got request schema {schema_name!r}"
    )
