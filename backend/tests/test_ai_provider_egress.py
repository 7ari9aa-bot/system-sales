"""§43 — provider data-egress governance on the real send path.

``AIProviderPolicyService.evaluate()`` sits inside ``AIGateway.chat`` /
``embed``, and ``decide()`` implements the precedence ladder — but the matrix
could not say ✅ because the parts the spec names were missing:

* **Classify** (§43's first pre-send step): ``chat``/``embed`` hardcoded
  ``data_class="internal"``, so a customer phone number in a prompt and a
  product brochure were indistinguishable to the policy — clearance could
  never block anything that mattered.
* **Data residency / retention** (policy fields the spec lists): absent
  entirely — a tenant with "EU data must not leave the EU" had nothing to
  declare and the gateway nothing to enforce.
* **Coverage**: every ``test_ai_governance`` case is a DB-free ``decide()``
  unit; nothing proved a denied policy actually stops the HTTP call, or that
  ``pii_redaction_required`` actually masks before send.

The pure-decide cases run everywhere; the send-path cases are CI-only.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.modules.ai import gateway as ai_gateway
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import AIProviderPolicy, ModelCall, ModelConfig
from app.modules.ai.policy import classify_data, decide

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _StubSettings:
    ai_provider_primary = "openai"
    ai_api_key_primary = "test-key"
    ai_base_url_primary = "https://api.test/v1"
    ai_model_primary = "gpt-test"


def _ok_chat_response(content: str = "pong") -> dict:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
    }


def _policy(**kw) -> AIProviderPolicy:
    fields = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        provider="openai",
        status="allowed",
        allowed_models=[],
        pii_redaction_required=False,
        data_classification="restricted",
    )
    fields.update(kw)
    return AIProviderPolicy(**fields)


# ---------------------------------------------------------------------------
# 1. §43 Classify — the payload decides the class, not the caller
# ---------------------------------------------------------------------------


def test_classify_data_detects_pii_in_message_content() -> None:
    clean = [{"role": "user", "content": "what is the warranty on the widget?"}]
    pii = [
        {
            "role": "user",
            "content": "call me on +20 100 555 7788 or email nour@example.com",
        }
    ]
    assert classify_data(clean) == "internal"
    assert classify_data(pii) == "restricted"


def test_classify_data_scans_embedding_texts_too() -> None:
    assert classify_data(["product brochure text"]) == "internal"
    assert classify_data(["my national id is 29811051234567"]) == "restricted"


def test_decide_denies_restricted_payload_above_clearance() -> None:
    """The gate only bites once the class is real: restricted payload against
    an internal-cleared provider must deny — the hardcoded "internal" caller
    made this branch unreachable for every PII prompt."""
    decision = decide(
        _policy(data_classification="internal"),
        provider="openai",
        model="gpt-test",
        data_class=classify_data([{"role": "user", "content": "card 4111 1111 1111 1111"}]),
    )
    assert decision.allowed is False
    assert "clearance" in decision.reason


# ---------------------------------------------------------------------------
# 2. §43 residency + retention declared, enforced, and honest when unknown
# ---------------------------------------------------------------------------


def test_decide_blocks_when_model_region_outside_residency() -> None:
    policy = _policy(data_residency="eu")
    decision = decide(
        policy, provider="openai", model="gpt-test", data_class="internal", region="us-east"
    )
    assert decision.allowed is False
    assert "residency" in decision.reason


def test_decide_blocks_when_residency_required_but_region_unknown() -> None:
    """Fail CLOSED: a tenant that declared EU residency must not have data
    shipped to a provider whose region nobody recorded."""
    policy = _policy(data_residency="eu")
    decision = decide(
        policy, provider="openai", model="gpt-test", data_class="internal", region=None
    )
    assert decision.allowed is False
    assert "unknown" in decision.reason


def test_decide_passes_when_region_matches_residency() -> None:
    policy = _policy(data_residency="eu")
    decision = decide(
        policy, provider="openai", model="gpt-test", data_class="internal", region="eu-west"
    )
    assert decision.allowed is True


def test_policy_carries_retention_terms_for_the_record() -> None:
    """§43: provider retention terms must be documented per policy — stored on
    the row so the trace/audit trail can answer "where did this data go".
    Enforcement is a provider contract, not a claim we make; declaring it on
    the model row is what the spec asks ("يجب توثيق provider
    data-processing terms/retention requirements")."""
    policy = _policy(retention_terms="30d, no training on customer data")
    assert policy.retention_terms == "30d, no training on customer data"


def test_router_exposes_the_new_governance_fields() -> None:
    """The upsert schema must accept residency + retention or staff cannot
    declare what §43 requires them to declare."""
    from app.main import create_app

    schema = create_app().openapi()["components"]["schemas"]
    fields = schema["ProviderPolicyUpsertRequest"]["properties"]
    assert {"data_residency", "retention_terms"} <= set(fields)


# ---------------------------------------------------------------------------
# 3. The send path honours the decision (CI Postgres)
# ---------------------------------------------------------------------------


async def test_chat_blocks_at_egress_before_any_http_call(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        AIProviderPolicy(
            tenant_id=tenant_id,
            provider="openai",
            status="denied",
            allowed_models=[],
            pii_redaction_required=False,
            data_classification="restricted",
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("provider must not be called for a denied provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError, match="data-egress"):
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )


async def test_chat_redacts_pii_when_policy_requires_it(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        AIProviderPolicy(
            tenant_id=tenant_id,
            provider="openai",
            status="allowed",
            allowed_models=[],
            pii_redaction_required=True,
            data_classification="restricted",
        )
    )
    await db.flush()

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json=_ok_chat_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await AIGateway().chat(
            db,
            tenant_id,
            alias="fast",
            messages=[
                {"role": "user", "content": "my email is nour@example.com, call +201005557788"}
            ],
            _client=client,
        )

    assert "nour@example.com" not in captured["body"]
    assert "[REDACTED_EMAIL]" in captured["body"]


async def test_chat_blocks_restricted_payload_above_clearance_on_the_send_path(
    db, tenant_ctx, monkeypatch
):
    """With classify wired in, a PII-bearing prompt against an
    internal-cleared provider is a policy violation, not a silent send."""
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        AIProviderPolicy(
            tenant_id=tenant_id,
            provider="openai",
            status="allowed",
            allowed_models=[],
            pii_redaction_required=False,
            data_classification="internal",
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("PII payload over clearance must not reach the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError, match="data-egress"):
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "email me at nour@example.com"}],
                _client=client,
            )


async def test_embed_honours_residency_before_calling_the_provider(
    db, tenant_ctx, monkeypatch
):
    """Embeddings ship customer text to the provider too — residency must stop
    that path, and an unknown region must fail closed."""
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        ModelConfig(
            tenant_id=tenant_id,
            alias="embedding",
            provider="openai",
            model="emb-test",
            config={"base_url": "https://api.test/v1", "api_key": "k"},
        )
    )
    db.add(
        AIProviderPolicy(
            tenant_id=tenant_id,
            provider="openai",
            status="allowed",
            allowed_models=[],
            pii_redaction_required=False,
            data_classification="restricted",
            data_residency="eu",
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("region-unknown embedding call must not happen")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError, match="data-egress"):
            await AIGateway().embed(db, tenant_id, texts=["any text"], _client=client)


# ---------------------------------------------------------------------------
# 4. S6 — the base_url itself is an egress surface
#
# A tenant-supplied ``model_configs.base_url`` used to be POSTed to verbatim,
# so a tenant could aim the gateway at cloud metadata (169.254.169.254), our
# own API behind the edge (localhost), or any RFC1918 host and read the
# response through error messages — with a deployment bearer key attached.
# providers.assert_provider_base_url now runs net_guard's rules before the
# request is built. These tests prove the refusal happens BEFORE any HTTP
# call, on the real gateway send path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_base_url",
    [
        "http://169.254.169.254/v1",  # cloud instance metadata (link-local)
        "http://localhost:8000/v1",  # our own API, past the edge
        "http://10.0.0.5:9000/v1",  # RFC1918 private literal
        "https://metadata.google.internal/v1",  # GCP metadata hostname
    ],
)
async def test_tenant_base_url_to_internal_target_is_refused_before_http(
    db, tenant_ctx, monkeypatch, bad_base_url
):
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        ModelConfig(
            tenant_id=tenant_id,
            alias="fast",
            provider="openai",
            model="cfg-model",
            config={"base_url": bad_base_url, "api_key": "cfg-key"},
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"request must never be issued to {bad_base_url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError):
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )


async def test_blocked_base_url_is_recorded_as_a_failed_model_call(
    db, tenant_ctx, monkeypatch
):
    """The refusal is a governed outcome, not a silent drop: a ModelCall row
    with status=error exists, and none of it carries the tenant's key."""
    tenant_id = tenant_ctx.tenant_id
    monkeypatch.setattr(ai_gateway, "get_settings", lambda: _StubSettings())
    db.add(
        ModelConfig(
            tenant_id=tenant_id,
            alias="fast",
            provider="openai",
            model="cfg-model",
            config={"base_url": "http://169.254.169.254/v1", "api_key": "cfg-key"},
        )
    )
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request may be issued")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError):
            await AIGateway().chat(
                db,
                tenant_id,
                alias="fast",
                messages=[{"role": "user", "content": "hi"}],
                _client=client,
            )

    row = (
        (await db.execute(select(ModelCall).where(ModelCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert row.status == "error"
    assert "cfg-key" not in str(row.__dict__)
