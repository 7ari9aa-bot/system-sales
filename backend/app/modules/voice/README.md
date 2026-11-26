# Voice Intelligence Platform — module map

Phase 0 (this branch) installs the contracts, not the audio. Nothing here streams a byte yet;
what it does is make the security shape of the platform testable before the first real call.

## The two planes
- **Control plane** (FastAPI core): who is calling, which shop, which persona, which scopes, is a
  session allowed. `security/capabilities.py` issues one frozen `SessionCapability` per session.
- **Media plane** (separate workers, later phases): audio in/out, WebRTC, SIP, barge-in, codecs.
  Long-lived, so it never lives inside a FastAPI request.

## What exists now
| file | what it fixes |
|---|---|
| `domain/personas.py` | two principals, never one prompt: merchant (read-only, authorized shop data) vs customer (public + verified own data) |
| `domain/states.py` | session and turn state machines; a human handoff is a one-way door, the agent cannot speak over staff |
| `domain/contracts.py` | `Fact` envelope: currency, period, timezone, as-of, completeness, evidence; refuses mixed currencies and partial totals |
| `security/capabilities.py` | server-side persona resolution, scope intersection with the user's real permissions, and a tool gateway that re-checks every call |
| `security/data_egress.py` | deny-by-default provider policy for audio; payment data never leaves |

## Invariants enforced in code (from the proposal, §20)
1, 2, 3, 5, 6, 7, 8, 9, 12 — see `tests/voice/test_voice_foundation.py`, which is pure (no DB, no
provider) on purpose.

## Next phases
1. Voice core: LiveKit media + session dispatcher + provider adapters.
2. Merchant voice intelligence: `MerchantIntelligenceGateway` over domain read services.
3. Customer voice: identity verification, context builder, handoff.
4. Telephony: SIP, DID routing, call state machine.
5. Omnichannel voice; 6. production hardening.
