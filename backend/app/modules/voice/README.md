# Voice Intelligence Platform (Sales OS)

Voice, built as architectural responsibilities inside this backend, not as eight services. The
control plane (identity, tenant, persona, entitlements, agent config) is separate from the media
plane (WebRTC/SIP, streaming audio, VAD, barge-in). Both run today; nothing here is deployed.

## The rule that shapes every file

**The runtime never decides permissions.** A session carries a `SessionCapability` minted by the
backend, and every tool call passes the `ToolGateway` first. Opening a session, a media credential
or a stream ticket also carries the text assistant's plan gate (`require_ai_entitlement`,
`CanUseAI`) — a plan that does not sell the AI agents is refused at 403 before a provider session
can open, with the same body the typed assistant returns. `merchant_assistant` is read-only over
one shop. `customer_agent` sees only the verified customer's own data. A prompt that asks for more
gets a refusal, because the refusal is in Python, not in the instructions.

## Layout

| Path | Responsibility |
| --- | --- |
| `security/personas.py`, `security/capabilities.py` | the two principals, session capability, tool gateway |
| `security/data_egress.py` | deny-by-default egress; a provider without an allowlisted policy carries nothing |
| `security/identity.py`, `security/channel_identity.py` | OTP verification, and handles that prove nothing until linked |
| `domain/contracts.py` | `Fact` envelope (value, currency, unit, period, timezone, as_of, completeness, evidence) and provider protocols |
| `domain/states.py`, `domain/calls.py` | session, turn, call and leg state machines |
| `domain/metrics.py`, `application/merchant_intelligence.py` | metric registry and the four read paths, no SQL |
| `application/session_manager.py`, `application/turn_orchestrator.py` | session lifecycle, turn orchestration through the gateway |
| `application/omnichannel.py`, `domain/channels.py` | voice notes on WhatsApp/Instagram/webchat under declared per-channel contracts |
| `application/inbound_calls.py`, `domain/routing.py`, `domain/recording.py` | signed, idempotent inbound calls; DID routing; recording consent |
| `application/hardening.py`, `domain/resilience.py` | circuit breakers, failover, cost ceilings, autoscale signal, quality scoring |
| `api/router.py` | the five `/api/v1/voice` endpoints |

## Production readiness review

Numbers below are what this repository actually measured, in the local test suite. There is **no
staging or production voice runtime yet**, so no load, chaos or latency figure in this document is a
production measurement, and none is presented as one.

**Correctness and safety**

- 135 voice tests, all green, in 0.48s of pure-Python execution (no database, no network).
- Gates green on top of that: `test_openapi_lock` (the HTTP surface cannot drift silently) and
  `test_contract_drift`.
- Invariants covered by tests, each with a named case: no merchant write path, no cross-tenant
  session (404, not 403), no cross-customer read, no merchant analytics from a customer session, no
  identity from a Caller ID or a channel handle, no recording without the mode the number declared,
  no second call for a retried webhook, no answer invented for an empty transcript.

**Failure behaviour**

- A provider is removed from routing after 3 consecutive failures (`CircuitBreaker`), and returns
  only through a single half-open probe: `tests/voice/test_voice_hardening.py`.
- A session survives a provider drop and resumes from the last completed turn: phase 1 recovery
  tests.
- A retried telephony webhook returns the existing call; a race is closed by
  `unique (tenant_id, provider_call_id)` in migration `fe2026112702`.

**Cost**

- Per-tenant monthly budget and per-call ceiling, checked *before* audio starts; an overrun is
  visible as a negative remainder and blocks the next call rather than reading as credit.
- Defaults: 50 000 minor units/month, 900s per call, 6 minor units per minute. These are defaults
  in code, not prices negotiated with anyone.

**Load**

- `RuntimeSnapshot` + `autoscale_action` give the signal a worker actually needs (live sessions,
  p95 turn time, failure rate), and shed new calls at capacity instead of dropping live ones. A
  worker that cannot report its capacity is treated as pressure, not as idle.
- The p95 threshold used by `evaluate_quality` is 2 500 ms; nothing has been measured against it on
  real infrastructure yet.

**Not done, deliberately**

- Migrations `fe2026112701` and `fe2026112702` are written and unapplied. Applying either to the
  live database needs the owner's explicit approval.
- No realtime, STT, TTS or telephony provider is configured; the adapters and their capability
  contracts exist, the credentials and the vendor choice do not.
- Rollback is a revert of the branch: nothing is merged to `main` and no live system reads this code.

## Where the numbered invariants are enforced

The numbering is the proposal's (§20). Each line is the file that refuses the wrong thing, and the
tests that pin it are the ones named in the module docstrings.

| Invariant | Enforced in | Proven by |
| --- | --- | --- |
| 1, 2, 3 | `security/personas.py`, `security/capabilities.py` — persona resolved from the authenticated principal, never the body | `test_voice_foundation.py` |
| 5, 6 | `domain/personas.py` — merchant has no write vocabulary; customer writes are named but do not exist in V1 | `test_voice_foundation.py` |
| 7 | `security/capabilities.py`, `domain/models.py` — permission re-checked per turn, so a revoked scope stops working mid-call | `test_voice_foundation.py`, `test_voice_core.py` |
| 8 | `security/capabilities.py` — scope intersection with the user's real permissions | `test_voice_foundation.py` |
| 9 | `domain/contracts.py`, `domain/states.py` — one state machine decides every move; provider-agnostic contracts | `test_voice_foundation.py`, `test_voice_core.py` |
| 12 | `security/data_egress.py` — deny-by-default egress, no proceeding by ignoring a warning | `test_voice_foundation.py` |
| 13 | `domain/metrics.py` — every metric carries its definition and version | `test_voice_merchant_intelligence.py` |
| 14 | `domain/states.py`, `domain/calls.py` — illegal transitions raise instead of being absorbed | `test_voice_foundation.py`, `test_voice_telephony.py` |

Tenant and customer isolation, idempotency and recording consent are proven in
`test_voice_router.py`, `test_voice_persistence.py`, `test_voice_customer.py` and
`test_voice_telephony.py`. The proposal's remaining numbered items (4, 10, 11, 15) are covered by the
same files at the level the code reaches today; the final review re-checks that mapping against the
proposal text rather than trusting this table.
