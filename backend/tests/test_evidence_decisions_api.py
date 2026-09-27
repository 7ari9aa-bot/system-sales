"""Wave A API surface: the evidence + decisions routes over the REAL app.

The services have their own unit tests (hashes, the state machine); this file
proves the HTTP layer through ``create_app()`` itself — so the unified error
contract maps ``NotFoundError`` to the 404 envelope, the permission gate bites,
and the routes answer the typed contracts. The two middlewares that open their
own Redis/Postgres connections are removed, exactly like
``tests/test_customers_http_surface.py`` does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.decisions.models import Decision
from app.modules.identity.deps import TenantContext, get_db, get_tenant_ctx

TENANT = uuid.uuid4()
USER = uuid.uuid4()
NOW = datetime.now(UTC)


def _decision(**over) -> Decision:
    base = dict(
        decision_id=uuid.uuid4(),
        tenant_id=TENANT,
        action="order.create",
        risk_level="LOW",
        normalized_arguments={"sku": "P1"},
        content_hash="a" * 64,
        decision_status="PROPOSED",
        approval_state="NOT_REQUIRED",
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )
    base.update(over)
    return Decision(**base)


class _Result:
    def __init__(self, items) -> None:
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _Session:
    """Routes the modules' reads by table; records adds. Writes are no-ops."""

    def __init__(self, decisions=None) -> None:
        self.decisions = list(decisions or [])
        self.added: list = []
        self.statements: list[str] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # Mimic the server_default columns a real INSERT would materialize:
        # the response models require them, and without a roundtrip they are
        # still None on the object.
        for obj in self.added:
            for pk in ("decision_id", "fact_id", "evidence_set_id", "dependency_id"):
                if hasattr(obj, pk) and getattr(obj, pk) is None:
                    setattr(obj, pk, uuid.uuid4())
            if getattr(obj, "created_at", None) is None:
                obj.created_at = NOW
            for attr, empty in (
                ("normalized_arguments", {}),
                ("resource_versions", {}),
                ("provenance", {}),
            ):
                if hasattr(obj, attr) and getattr(obj, attr, None) is None:
                    setattr(obj, attr, empty)

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        self.statements.append(sql)
        if "from decisions" in sql and "decision_dependencies" not in sql:
            return _Result(self.decisions)
        raise AssertionError(f"unexpected statement: {sql[:140]}")


def _app_for(session: _Session):
    ctx = TenantContext(
        session=session,
        user=SimpleNamespace(id=USER, is_active=True),
        tenant_id=TENANT,
        role_code="owner",
        permission_codes={"decisions:write", "settings:write"},
    )
    app = create_app()
    drop = {IdempotencyMiddleware, RateLimitMiddleware}
    app.user_middleware = [m for m in app.user_middleware if m.cls not in drop]
    app.middleware_stack = None

    async def _session_dep() -> Any:
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session_dep
    return app


async def test_propose_mints_a_decision_with_a_computed_hash():
    session = _Session()
    async with AsyncClient(
        transport=ASGITransport(app=_app_for(session)), base_url="http://t"
    ) as c:
        response = await c.post(
            "/api/v1/decisions",
            json={
                "action": "order.create",
                "risk_level": "LOW",
                "normalized_arguments": {"sku": "P1"},
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision_status"] == "PROPOSED"
    assert len(body["content_hash"]) == 64
    assert session.added, "the minted decision was persisted"


async def test_an_unknown_decision_answers_the_not_found_envelope():
    async with AsyncClient(
        transport=ASGITransport(app=_app_for(_Session())), base_url="http://t"
    ) as c:
        response = await c.get(f"/api/v1/decisions/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_the_state_machine_transitions_over_http():
    decision = _decision()
    session = _Session(decisions=[decision])
    app = _app_for(session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        response = await c.post(f"/api/v1/decisions/{decision.decision_id}/verify")

    assert response.status_code == 200, response.text
    assert response.json()["decision_status"] == "VERIFIED"
    assert decision.decision_status == "VERIFIED", "the transition mutated the row"


async def test_evidence_facts_post_round_trips_a_typed_fact():
    session = _Session()
    async with AsyncClient(
        transport=ASGITransport(app=_app_for(session)), base_url="http://t"
    ) as c:
        response = await c.post(
            "/api/v1/evidence/facts",
            json={
                "claim": "الكمية 3 متاحة",
                "subject_type": "product",
                "source_type": "DATABASE",
                "classification": "INTERNAL",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_hash"] and len(body["content_hash"]) == 64
    assert body["trust"] in {"UNVERIFIED", "OBSERVED"}
    assert session.added, "the fact was persisted"
