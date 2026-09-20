"""DB-free tests for the Job control surface (§84), SavedView (§95) and the
health indicator (§103).

The routes themselves need a database and a request context, so these tests
drive the pure decision logic — the retry/cancel rules, the saved-view
visibility rule, and the health assembly — plus the model invariants that the
migration has to satisfy. Route mounting is asserted through the OpenAPI schema
because ``app.routes`` only shows an ``_IncludedRouter`` placeholder.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.main import create_app
from app.modules.operations.router import job_can_cancel, job_can_retry
from app.modules.platform.models import Job, SavedView
from app.modules.platform.router import (
    _database_subsystem,
    build_health_response,
    can_modify_saved_view,
    can_read_saved_view,
    integration_health,
    overall_health_status,
    subsystem,
)

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER = uuid.UUID("22222222-2222-2222-2222-222222222222")
WRITE = {"settings:write"}


# ---------------------------------------------------------------- jobs ----


def test_retry_is_refused_on_a_completed_job() -> None:
    """The work already happened; re-running could repeat a side effect."""
    assert job_can_retry("completed") is False


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_retry_is_allowed_once_a_run_has_stopped(status: str) -> None:
    assert job_can_retry(status) is True


@pytest.mark.parametrize("status", ["queued", "processing", "retrying"])
def test_retry_is_refused_while_the_job_is_still_in_flight(status: str) -> None:
    assert job_can_retry(status) is False


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_cancel_is_refused_on_every_terminal_job(status: str) -> None:
    assert job_can_cancel(status) is False


@pytest.mark.parametrize("status", ["queued", "processing", "retrying"])
def test_cancel_is_allowed_while_the_job_is_still_in_flight(status: str) -> None:
    assert job_can_cancel(status) is True


def test_job_is_tenant_scoped_and_not_workspace_scoped() -> None:
    """No WorkspaceScopeMixin — so the migration must not create those columns."""
    columns = set(Job.__table__.c.keys())
    assert "tenant_id" in columns
    assert {"workspace_id", "location_id"}.isdisjoint(columns)


# --------------------------------------------------------- saved views ----


def _view(visibility: str, owner: uuid.UUID | None = USER) -> SavedView:
    return SavedView(
        tenant_id=uuid.uuid4(),
        name="My view",
        entity="customers",
        definition={"filters": [], "sort": "-created_at"},
        visibility=visibility,
        owner_user_id=owner,
    )


def test_a_private_view_is_modifiable_only_by_its_owner() -> None:
    view = _view("private")
    assert can_modify_saved_view(view, user_id=USER, permission_codes=set()) is True
    # settings:write does NOT let someone else rewrite a private view.
    assert can_modify_saved_view(view, user_id=OTHER, permission_codes=WRITE) is False


def test_a_workspace_view_requires_settings_write_even_for_its_owner() -> None:
    view = _view("workspace")
    assert can_modify_saved_view(view, user_id=USER, permission_codes=set()) is False
    assert can_modify_saved_view(view, user_id=USER, permission_codes=WRITE) is True
    assert can_modify_saved_view(view, user_id=OTHER, permission_codes=WRITE) is True


def test_a_team_view_is_modifiable_by_its_owner_or_a_settings_writer() -> None:
    view = _view("team")
    assert can_modify_saved_view(view, user_id=USER, permission_codes=set()) is True
    assert can_modify_saved_view(view, user_id=OTHER, permission_codes=set()) is False
    assert can_modify_saved_view(view, user_id=OTHER, permission_codes=WRITE) is True


def test_an_unknown_visibility_is_denied_not_guessed() -> None:
    view = _view("everyone")
    assert can_modify_saved_view(view, user_id=USER, permission_codes=WRITE) is False


def test_a_private_view_is_readable_only_by_its_owner() -> None:
    assert can_read_saved_view(_view("private"), user_id=USER) is True
    assert can_read_saved_view(_view("private"), user_id=OTHER) is False
    for visibility in ("team", "workspace"):
        assert can_read_saved_view(_view(visibility), user_id=OTHER) is True


# -------------------------------------------------------------- health ----


def test_overall_status_is_the_worst_subsystem_status() -> None:
    healthy = [subsystem("database", "healthy"), subsystem("redis", "healthy")]
    assert overall_health_status(healthy) == "healthy"
    assert overall_health_status([*healthy, subsystem("dlq", "degraded")]) == "degraded"
    assert (
        overall_health_status([*healthy, subsystem("dlq", "degraded"), subsystem("redis", "down")])
        == "down"
    )
    assert overall_health_status([]) == "healthy"


def test_integration_health_maps_webhook_failures() -> None:
    # A freshly connected integration has never failed — not degraded.
    assert integration_health({}) == "healthy"
    assert integration_health(None) == "healthy"
    assert integration_health({"consecutive_failures": 0}) == "healthy"
    assert integration_health({"consecutive_failures": 1}) == "degraded"
    assert integration_health({"consecutive_failures": 5}) == "down"
    # A malformed snapshot must not raise.
    assert integration_health({"consecutive_failures": "lots"}) == "healthy"


class _RaisingSession:
    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("postgresql://user:pw@host/db is unreachable")


class _FakeCtx:
    def __init__(self, session: object) -> None:
        self.session = session
        self.tenant_id = uuid.uuid4()


async def test_a_failing_subsystem_is_reported_not_raised_and_leaks_nothing() -> None:
    """A health check that 500s (or echoes the driver's DSN) is useless."""
    row = await _database_subsystem(_FakeCtx(_RaisingSession()))
    assert row["status"] == "down"
    assert "RuntimeError" in row["detail"]
    assert "postgresql://" not in row["detail"]
    assert "pw" not in row["detail"]


_SECRET_KEY = re.compile(
    r"secret|password|token|credential|dsn|api[_-]?key|connection|conn_str|uri|url",
    re.IGNORECASE,
)


def _walk(node: object):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, str):
        yield node


def test_health_response_has_no_secret_looking_keys_or_values() -> None:
    response = build_health_response(
        [
            subsystem("database", "healthy"),
            subsystem("redis", "degraded", "unreachable (OSError)"),
            subsystem("outbox", "healthy", "no pending events"),
            subsystem("dlq", "down", "12 dead-lettered events"),
            subsystem("integrations", "degraded", "1 of 2 integrations failing")
            | {"integrations": [{"provider": "whatsapp", "status": "degraded"}]},
        ]
    )
    assert set(response) == {"status", "subsystems"}
    assert response["status"] == "down"

    for item in _walk(response):
        assert not _SECRET_KEY.search(item), item
        assert "://" not in item, item


# ------------------------------------------------------------- mounting ---


def test_job_saved_view_and_health_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/retry",
        "/api/v1/jobs/{job_id}/cancel",
        "/api/v1/platform/saved-views",
        "/api/v1/platform/saved-views/{view_id}",
        "/api/v1/platform/health",
    } <= paths
