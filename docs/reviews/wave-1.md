# Wave-1 Security Review

Scope: §164 tenant restore, §136 n8n service tokens, §146 MFA, §59/§147 break-glass,
§66 audit lineage, §68/§69 secrets at rest. Spec sources:
`docs/spec/ARCHITECTURE_SPEC_1-124.txt` (§59, §66–69), `docs/spec/ARCHITECTURE_PATCH_125-177.txt`
(§136, §146, §147, §164 — patch wins). Review method: read spec clause, read implementation,
hunt for gaps / holes / inconsistencies / broken edge cases. No fixes applied.

---

## Blockers

**B1. Break-glass elevation consumer writes a column that does not exist — suspend/reactivate is a silent no-op.**
`backend/app/modules/platform/router.py:623` does `tenant.status = status`, but the `Tenant`
ORM model (`backend/app/modules/identity/models.py:29-61`) and the `tenants` table
(`backend/migrations/versions/0b79f7470c1a_stage1_full_schema_63_tables.py`) have **no
`status` column** — the §48 enforcement field is `lifecycle_state`, read by
`identity/deps.py:196-209`, `identity/service.py:231`, and `workers/base.py:78-87`. Setting an
unmapped attribute flushes nothing, so the endpoint burns the one-shot capability, returns
`200 {"status": "suspended"}`, and changes nothing. It also bypasses
`TenantLifecycleService.transition` (`identity/service.py:851-892`), the documented single
writer that keeps `is_active` consistent and writes the before/after audit row. Sibling
endpoints `GET /platform/admin/tenants` and `GET /platform/admin/tenants/{id}`
(`platform/router.py:520-527, 568-577`) select `Tenant.status`/`Tenant.plan`, which also do
not exist, so they 500 on first call.
Spec: §147 (the elevation must actually work), §48.
Fix: route the mutation through `TenantLifecycleService.transition(...)` (or map a real
column) and drop the phantom `status`/`plan` selects.

**B2. Platform-admin gate checks a tenant permission code that nothing can ever grant.**
`_require_platform_admin` (`platform/router.py:43-52`) requires `"platform_admin"` inside
`ctx.permission_codes` — codes coming from the caller's **tenant role** via
`identity/deps.py:211-221`. Nothing in the codebase seeds a `platform_admin` permission
(grep-clean), so in production every admin-plane route — including
`POST /platform/admin/break-glass` (`platform/router.py:706`) and the status consumer — is
unreachable, contradicting the file's own §160 claim that a platform admin needs no tenant
membership (`TenantCtxDep` itself 403s non-members at `deps.py:187-188` first). The correct
gate already exists and is unused: `require_platform_admin` (`deps.py:265-273`) checks the
JWT `is_platform_admin` claim issued at `identity/service.py:456-461`. Worse, the obvious
operator workaround (grant a `platform_admin` permission to a tenant role) instantly turns a
plain tenant user into a cross-tenant admin who can mint break-glass capabilities for **any**
`tenant_id`. Tests hide this by fabricating `permission_codes={"platform_admin"}`
(`backend/tests/test_webhook_retry.py:274`).
Spec: §146 (platform access model), §147, §160.
Fix: gate on `ctx.user.is_platform_admin` (use `require_platform_admin`) and drop the
permission-code check.

---

## Majors

**M1. TOTP secrets are stored as base64, not encrypted — §68 violation inside the same wave.**
`backend/app/core/mfa.py:125-131` `_encrypt_secret`/`_decrypt_secret` are plain base64; the
model and migration admit it (`identity/models.py:96-97`,
`migrations/versions/c146bb146bb1_user_mfa_secrets.py:37`: "envelope encryption lands with the
§68/69 work"). But §68/§69 **is** this wave — `EnvelopeSecretStore` shipped in
`backend/app/core/secrets.py` and is never used here. A DB dump yields every user's TOTP
seed in reversible form = full MFA bypass.
Spec: §68 ("secrets must be encrypted"), §146.
Fix: encrypt TOTP secrets with `EnvelopeSecretStore` (lazy-migrate like credentials).

**M2. MFA backup codes can never be used at login — lost authenticator = permanent lockout.**
`check_challenge_code` (`mfa.py:320-355`) verifies only TOTP via `verify_mfa`
(`mfa.py:204-209`); backup codes are honored solely by `disable_mfa` (`mfa.py:212-238`),
which sits behind `CurrentUserDep` (`identity/router.py:194-202`) — i.e. behind a login that
itself requires MFA. The 8 recovery codes issued at `confirm_mfa` are therefore useless for
the one scenario they exist for.
Spec: §146.
Fix: accept a backup code in `/auth/mfa/verify` (hash-compare, one-time consume).

**M3. §136 inbound half is missing: nothing verifies per-tenant tokens.**
`verify_token` (`backend/app/modules/automation/tokens.py:81-112`) has **zero callers** in
`app/`; no n8n→core callback endpoint or auth dependency accepts `tst_` tokens, and the
`automation:callback` scope has no consumer. Meanwhile the "replaced" global
`SERVICE_TOKEN_INTERNAL` is still a **mandatory production secret**
(`backend/app/core/config.py:160-161`) and still drives the middleware's service-actor
detection (`backend/app/main.py:118-125`) — so the deprecated unrestricted token must keep
existing while the new scoped tokens authenticate nothing.
Spec: §136 ("n8n callback uses tenant-scoped credential/token; never a global unrestricted
token").
Fix: add the callback auth dependency on `verify_token` (scope `automation:callback`) and
retire the global-token path.

**M4. Token lifecycle leaks: unbounded accumulation of valid tokens + no management surface.**
`get_or_issue_outbound_token` (`tokens.py:192-205`) caches plaintext per process and, after
every restart/deploy, issues a **new** `n8n-outbound` token without revoking the old ones;
each instance holds its own. Plaintexts are unrecoverable by design, and there is no API to
list/rotate/revoke (`automation/router.py` has no token routes; `issue/rotate/revoke_token`
are library-only). Every stale token stays valid forever.
Spec: §136 (revocable per-tenant credentials), §69 (rotation discipline).
Fix: persist/revoke on re-issue (single active outbound token per tenant) and expose
management endpoints behind `settings:write`.

**M5. The privileged tenant-status mutation itself is never audited.**
`PATCH /platform/admin/tenants/{id}/status` (`platform/router.py:580-628`) writes no
`AuditLog` (before/after) and no `SecurityEvent`; the only paper trail is the break-glass
*issuance* event, which may be minutes old and names a different resource. §147 demands every
break-glass access in audit; §66 demands before/after on important mutations. (Currently
masked by B1 — nothing mutates at all.)
Spec: §147, §66.
Fix: write an audit row (old→new state) + SecurityEvent in the same transaction as the
mutation.

**M6. §66 `source` vocabulary does not match the spec.**
Spec §66 defines sources `human | ai | automation | system | integration`; the implementation
uses `user | service | worker | ai` (`backend/app/core/context.py:8-12`,
`platform/service.py:80`, `main.py:120-125`, `workers/base.py:260`). `automation`, `system`
and `integration` can never appear, so §66's "AI actions must be distinguishable" and
automation attribution are unenforceable downstream; n8n-originated writes would be labeled
`user` (see M3).
Spec: §66.
Fix: adopt the spec vocabulary (map `user→human`, `service/worker→automation|system`).

**M7. `tenant_restore_jobs` RLS is weaker than every other tenant table and than the service claims.**
Created in `backend/migrations/versions/f9b0c1d2e3f4_phase9_external_voice_saga_growth.py:331-350,385-407`
**after** the FORCE-RLS sweep (`b2c3d4e5f6a7`), the table gets ENABLE-only RLS (no FORCE, so
a table-owner app role bypasses it) and a policy using bare `current_setting('app.tenant_id')::uuid`
— which **raises** when the GUC is unset — instead of the canonical
`NULLIF(current_setting('app.tenant_id', true), '')::uuid` used by the §136 token table
(`c136aa136aa1:31,78-80`). The service docstring's guarantee ("FORCE RLS makes cross-tenant
access impossible", `tenant_restore.py:124-128`) does not hold for its own job table.
Spec: §164, §11.
Fix: add FORCE RLS + the canonical guard policy (mirroring c136aa136aa1).

**M8. Tenant secret rotation emits no security event and no audit.**
`SecretService.rotate_secret` (`backend/app/modules/platform/service.py:186-215`) updates the
reference row only: no `SecurityEvent(secret_rotated)`, no `AuditService.write`, no outbox
event — while `rotate_master_key` does emit `platform.secret_rotated`
(`backend/app/core/secrets.py:455-466`). §67 lists "Secret rotated" as a security event and
§69's rotation flow ends with "audit".
Spec: §67, §69.
Fix: write SecurityEvent + audit (or the same outbox event) on every rotation.

**M9. Secret write endpoints have no authorization gate.**
`POST /platform/secrets` and `POST /platform/secrets/{provider}/rotate`
(`platform/router.py:768-820`) take plain `TenantCtxDep` — any authenticated tenant member
can register or rotate secrets, unlike every comparable surface (flags, integrations, saved
workspace views all require `settings:write`). §68 requires secrets to be access-controlled;
§67 expects "API key created" events, which are also absent here.
Spec: §68, §12, §67.
Fix: gate both endpoints with `require_permission("settings:write")`.

**M10. Master-key rotation is process-local, non-persistent, and unreachable.**
`rotate_master_key` (`secrets.py:441-467`) swaps only the in-process singleton: other API
instances keep encrypting/decrypting with the old key (they cannot read new-key ciphertexts
→ cross-instance failures during the grace window), and a restart reverts to
`SECRETS_MASTER_KEY` — rows lazily re-encrypted under the new key then raise
`SecretDecryptionError`. There is also no caller (no endpoint/CLI; tests only). §69's "never
break every request at once" is violated across a multi-instance deployment (§59).
Spec: §69, §59.
Fix: drive rotation from config across instances (ring in env), add an ops entry point, and
re-encrypt rows before retiring a key.

**M11. Integration re-upsert silently wipes stored credentials.**
`IntegrationBody.credentials` defaults to `{}` (`backend/app/modules/customers/router.py:314`)
and the update branch assigns wholesale: `existing.credentials = encrypt_credentials_dict(body.credentials)`
(`customers/router.py:425`). A config-only refresh (the documented idempotent re-register
path) therefore erases the tenant's channel secrets; the next outbound send fails after
decrypting an empty dict. Broken rotation-during-traffic edge case.
Spec: §68, §145.
Fix: treat absent/`{}` credentials as "keep existing" (merge semantics) or require explicit
null to clear.

**M12. MFA enrollment requires no step-up authentication.**
`/auth/mfa/enroll` + `/auth/mfa/confirm` (`identity/router.py:176-191`,
`mfa.py:148-195`) need only a valid access token. A stolen token lets an attacker enroll
*their* authenticator and lock the real user out at the next login (token theft → durable
account takeover).
Spec: §146.
Fix: require a fresh password (or existing TOTP) to enroll/confirm.

---

## Minors

**m1.** Backup codes: 40-bit entropy (`py_secrets.token_hex(5)`) hashed with unsalted SHA-256
(`mfa.py:134-139`) — offline-crackable from a DB dump. §146. Fix: 8+ byte codes or a slow KDF.

**m2.** TOTP replay: no last-used counter tracking — an intercepted code is reusable within
its ±30s window against a fresh challenge (`mfa.py:91-104`). §146/RFC 6238 one-time use.

**m3.** No attempt limiting on `confirm_mfa`/`disable_mfa` — authenticated online guessing of
the 10^6 code space is unbounded (`mfa.py:179-195, 212-238`). §146.

**m4.** Challenge farming: a valid password mints unlimited concurrent challenges (5 tries
each) — no per-user cap (`mfa.py:254-267`; `identity/service.py:307-309`). §146.

**m5.** Break-glass issuance drops client metadata: router passes `ip=None, user_agent=None`
though `break_glass` accepts them (`platform/router.py:709-719`). §147 audit completeness.

**m6.** Capability is burned before request validation: `validate_capability` runs before the
status whitelist/tenant-existence checks, so a bad request destroys the one-shot token
(`platform/router.py:597-622`); and `status` is a query param defaulting to `"active"`, so a
param-less PATCH reactivates instead of suspending. §147 edge case.

**m7.** `validate_capability` ignores `resource_type`/`resource_id` (`break_glass.py:175-179`)
— §147's "explicit scope" is recorded at issuance but not enforced at consumption; a
capability works for any resource of the same tenant+action.

**m8.** `POST /platform/admin/break-glass/validate` consumes the token it validates
(`platform/router.py:731-746`) — a "check" that destroys; inconsistent with its name/docstring.

**m9.** Break-glass audit vs capability split-transaction: audit rows flush on the request
transaction while the capability lands in Redis — a post-SET rollback leaves a live,
unaudited capability (`break_glass.py:78-123`). The login-failure path already solved this
class with dedicated transactions (`identity/service.py:264-271`).

**m10.** Honored `x-request-id`/`x-correlation-id` are unvalidated (`main.py:107-111`): >64
chars breaks the `audit_logs` INSERT (`String(64)`, `platform/models.py:117-118`) and
arbitrary values pollute §66 lineage. Fix: length/charset-validate, else regenerate.

**m11.** Middleware service-token comparison is non-constant-time and case-insensitive
(`main.py:118-125`) — timing oracle + case-collapsed matching on the (deprecated) global token.

**m12.** `verify_token` reveals token state via distinct errors
(invalid / revoked / missing-scope / foreign-tenant, `tokens.py:97-109`) — enumeration oracle.

**m13.** `EnvSecretStore` remains the production default (`secrets.py:171-172`): unlike the
master key, nothing in `config.Settings` refuses to boot in secure environments without a real
Vault/KMS adapter. §68.

**m14.** SSO identity links live in Redis with no TTL (`mfa.py:394, 420`) — eviction silently
un-links accounts (self-heals via email match, but §59 assigns durable state to Postgres); SSO
login also bypasses MFA entirely for MFA-enabled users (`mfa.py:373-426`) — undocumented.

**m15.** SSO email-linking trusts the assertion email to attach to an existing local account
(`mfa.py:404-409`) — takeover if the IdP email is unverified; the "already verified"
precondition is asserted only in the docstring.

**m16.** Tenant-restore job creation validates nothing: unknown `entity_types` are accepted and
fail the job only at extraction (`tenant_restore.py:132-164, 190-205`); future `backup_point`
values are accepted; and validate→execute with no extract completes a zero-work job while
emitting `tenant.restore.completed` + an audit row (`tenant_restore.py:216-282, 340-368`) —
falsifies the §66/§164 trail.

**m17.** Dead states `RESTORING_SNAPSHOT`/`CANCELLED` have no producers
(`tenant_restore.py:68-76`); `recovery_db_ref`/`recovery_session` PITR variant is unwired.
Also `_restore_job_payload` can return up to 10k staged ids per response
(`platform/router.py:843-855`, `tenant_restore.py:63`).

**m18.** `TenantRestoreStatus` values (`restoring` = "validated, ready") are reused as both
gate and state (`tenant_restore.py:280, 303`) — readable but fragile; consider an explicit
`validated` state. (Style; listed for completeness.)

---

## Clean / verified areas

- §136 token storage: sha256-digest-only, unique digest index, FORCE RLS with canonical
  guard, constant-time-by-construction verify, rotation chain auditable, outbox events
  (`automation.service_token.issued/revoked`) registered in the closed `DOMAIN_EVENT_TYPES`
  set (`core/events/schemas.py:92-123`). Clean apart from M3/M4/m12.
- §146 challenge flow: single-use GETDEL consume with race handling, 5-strike lock, TTL,
  unified "invalid credentials" + dummy-hash timing defense at login, disabled-account
  re-check at `mfa_verify`. Solid apart from M1/M2/M12 and m1–m4.
- §147 capability store: Redis TTL, atomic GETDEL one-shot, mismatched-presentation burn,
  reason ≥10 chars, dual AuditLog+SecurityEvent at issuance, admin notification with dedup
  key. Solid apart from m5–m9.
- §66 lineage plumbing: contextvars → middleware (HTTP) and worker runtime (bus events) →
  `AuditService` (never caller-supplied); `audit_logs` NO-FORCE + NULL-tenant policy is a
  deliberate, documented exception (`b2c3d4e5f6a7:190-199`). Clean apart from M6/m10.
- §68 envelope crypto: AES-256-GCM with per-value DEK + HKDF KEK, AAD separation, key ring
  for grace-period decrypts, tamper → raise (never silent), legacy-plaintext pass-through
  flagged, canary-validated rotation, secure-env master-key enforcement
  (`core/config.py:162-171`). Encrypt-on-write (`customers/router.py:425,445`) and audited
  batched decrypt-on-send (`workers/message_worker.py:341-354`) verified; no plaintext
  credential reads anywhere else. Clean apart from M8–M11/m13.
- §164 restore core logic: tenant-binding discipline, id-cap manifests, intentional-delete
  (privacy) protection, validate-before-execute gate, conflict-fails-closed, atomic
  flush-only transactions, cross-tenant test coverage. Clean apart from M7/m16–m18.

---

WAVE-1 REVIEW: 2 blockers, 12 majors, 18 minors.
