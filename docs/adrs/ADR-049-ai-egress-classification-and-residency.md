# ADR-049: AI Egress Classification and Data Residency

- **Status:** Accepted
- **Date:** 2026-09-23
- **Spec:** §43 (AI provider data governance)
- **Related:** ADR-036 (memory governance), `docs/COMPLIANCE_MATRIX.md` §43

## Context

§43 requires that, before any data leaves the tenant boundary to an AI
provider, the system runs:

```text
Classify → Redact / Mask PII where required → Apply tenant/provider policy → Send
```

`AIProviderPolicyService.evaluate()` was already on both egress paths
(`AIGateway.chat`, `AIGateway.embed`), and `pii_redaction_required` genuinely
masked the payload. Two of the four steps were still fiction:

1. **Classify** — the callers passed `data_class="internal"` as a literal.
   Every prompt — a warranty question and a customer's phone number — arrived
   at the policy engine with the same class, so the clearance ladder
   (`public < internal < confidential < restricted`) could never block real
   PII. A tenant whose provider was cleared for `internal` only was protected
   exactly as much as one with no policy at all: not at all.
2. **Residency / retention** — the spec lists both as per-tenant policy fields.
   The row had neither, so there was nothing to declare and nothing to enforce.

The matrix kept §43 at 🟡 citing "no caller on the egress path", which was
already stale — the honest gap was *what the caller passed*, not *whether it
called*.

## Decision

### 1. The payload classifies itself

`policy.classify_data(payload)` accepts provider messages, embedding texts, or
a plain string, and returns `restricted` when the text carries a direct
identifier (email, phone, card number, national ID) and `internal` otherwise.
The patterns are the same shapes `_redact_pii` masks, so the classifier and
the redactor cannot disagree about what PII is.

The classifier is deliberately coarse: two rungs that our flows actually
produce, not a DLP taxonomy. Tool-call arguments are not scanned — they are
server-side bound and already tenant-scoped (§132).

### 2. Redaction can downgrade, but the gate still decides

Per the spec's order, the gateway evaluates the *classified* payload first;
when the policy demands redaction it masks, re-classifies, and re-applies the
policy. So a `restricted` email prompt to an `internal`-cleared provider is:

- **allowed** when the policy sets `pii_redaction_required` (the mask brings
  the payload within clearance), and
- **blocked** when it does not — the data would leave as-is, above clearance.

That distinction is the whole point of the flag, and it is only expressible
because the class is computed instead of declared.

### 3. Residency fails CLOSED; retention is documented, not claimed

`AIProviderPolicy.data_residency` holds a region token ("eu", "me"). At
decision time it compares against the `region` key of the resolved model
config (substring match both ways, so `eu` matches `eu-west-1`).

**A declared residency with an unknown provider region denies the call.**
"We don't know where this runs" is not evidence that it runs inside the
residency the tenant declared. Operators unblock it by recording the region
on the model config — the fix is information the tenant owns, which is what
fail-closed is for.

`AIProviderPolicy.retention_terms` stores the provider's data-processing /
retention terms on the policy row. We do not *enforce* a provider's retention
from our side of the wire; §43 asks that the terms be documented before
production, and storing them on the same row the egress gate reads is what
makes "where did this data go, for how long" answerable in an audit.

### 4. Rejected alternatives

- **Keep `data_class` caller-declared, make call sites pass real values.**
  Rejected: it scatters the policy across N call sites and every future call
  site is a chance to under-classify again. The egress path is the last place
  all the text is together — classify it there.
- **Classify with an LLM.** Rejected: sends the payload to a model to decide
  whether sending the payload is allowed — circular, and costs money to make
  a safety decision.
- **Residency as a warning, not a block.** Rejected: the fail-open default in
  this module exists for tenants with *no* policy; a tenant that explicitly
  declares a residency has exercised the opposite right — an unrecorded
  region must not silently override a stated constraint.
- **Storing provider regions in code (a static provider→region map).**
  Rejected: providers serve multiple regions from one name; the truth belongs
  on the tenant's own model config, next to the base_url that says which
  endpoint they picked.

## Consequences

- Migration `f6c9e3a1b5d8_*` adds `data_residency` / `retention_terms`
  (nullable; existing policies unchanged = no residency declared).
- `decide()` takes a `region` keyword; `evaluate()` forwards it. The
  precedence ladder is deny → model allow-list → residency → clearance →
  allow, pinned in `tests/test_ai_governance.py` (pure) and
  `tests/test_ai_provider_egress.py` (send path: blocked before any HTTP
  call, masked body on the wire, fail-closed residency on embed).
- Classifying the same text twice (chat + embed) is two regex passes over a
  prompt — negligible next to the HTTP request it guards.
- A tenant with `pii_redaction_required=False` and a low clearance will now
  start seeing `data-egress` rejections on prompts that contain contact
  details. That is the policy working, but it is a behavior change: the
  alerting and docs for operators should name the reason string
  (`exceeds provider ... clearance`) so support can tell it from a bug.
