"""Focused, DB-free tests for the privacy / segments / automation routers.

The routers need auth + a database to exercise end to end, so these tests cover
what is pure logic: the segment DSL whitelist (a bad definition must raise
``ValidationError`` — HTTP 400, never a 500), the service-level validation the
routers rely on, and proof that every new route is actually mounted.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.automation.service import WorkflowService
from app.modules.privacy.service import DataRequestService
from app.modules.segments.router import SegmentPreviewRequest, preview_segment
from app.modules.segments.service import validate_dsl

GOOD_DEFINITION = {
    "all": [
        {"field": "orders_count", "op": "gt", "value": 3},
        {"field": "lifetime_value", "op": "gt", "value": 500},
        {"field": "source", "op": "eq", "value": "instagram"},
    ]
}


# --------------------------------------------------- segment DSL whitelist --


def test_validate_dsl_accepts_documented_shapes() -> None:
    validate_dsl(GOOD_DEFINITION)
    validate_dsl({"any": [{"field": "has_email", "op": "eq", "value": True}]})
    validate_dsl({"not": {"field": "is_blocked", "op": "eq", "value": True}})
    validate_dsl({"all": [{"field": "source", "op": "in", "value": ["a", "b"]}]})
    validate_dsl({"all": [{"field": "source", "op": "contains", "value": "insta"}]})


@pytest.mark.parametrize(
    "definition",
    [
        "not-an-object",
        {},
        {"all": []},
        {"any": "nope"},
        {"all": [{"field": "password", "op": "eq", "value": 1}]},
        {"all": [{"field": "source", "op": "drop_table", "value": "x"}]},
        {"all": [{"field": "source", "op": "eq"}]},
        {"all": [{"field": "source", "op": "eq", "value": "x"}], "extra": 1},
        {"not": {"field": "source", "op": "eq", "value": "x"}, "all": []},
    ],
)
def test_validate_dsl_rejects_bad_definitions(definition: object) -> None:
    with pytest.raises(ValidationError):
        validate_dsl(definition)


async def test_segment_preview_rejects_bad_dsl_before_touching_the_session() -> None:
    """A bad DSL fails as ValidationError before any DB access (400, not 500)."""
    ctx = SimpleNamespace(tenant_id=uuid.uuid4(), session=None)
    body = SegmentPreviewRequest(definition={"field": "password", "op": "eq", "value": "x"})
    with pytest.raises(ValidationError):
        await preview_segment(ctx, body)


# --------------------------------------------- service-level validation ------


async def test_workflow_create_rejects_bad_definition_without_db() -> None:
    with pytest.raises(ValidationError):
        await WorkflowService.create(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            name="wf",
            trigger_event="order.created",
            definition={"not_steps": True},
        )


async def test_data_request_create_rejects_unknown_type_without_db() -> None:
    with pytest.raises(ValidationError):
        await DataRequestService.create(
            None,  # type: ignore[arg-type] — raises before the session is used
            uuid.uuid4(),
            customer_id=uuid.uuid4(),
            request_type="bogus",
        )


# ------------------------------------------------------------ route mounting -


def test_new_module_routers_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    expected = {
        "/api/v1/privacy/consents",
        "/api/v1/privacy/consents/{consent_id}/revoke",
        "/api/v1/privacy/data-requests",
        "/api/v1/privacy/data-requests/{request_id}",
        "/api/v1/privacy/data-requests/{request_id}/execute",
        "/api/v1/segments",
        "/api/v1/segments/preview",
        "/api/v1/segments/{segment_id}",
        "/api/v1/workflows",
        "/api/v1/workflows/executions/{execution_id}/run",
        "/api/v1/workflows/{workflow_id}",
        "/api/v1/workflows/{workflow_id}/executions",
        "/api/v1/workflows/{workflow_id}/status",
        "/api/v1/workflows/{workflow_id}/versions",
    }
    assert expected <= paths
