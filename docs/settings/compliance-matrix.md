# Settings Compliance Matrix

> Auto-generated from the codebase by `scripts/dev/gen_compliance_matrix.py`.
> Do not edit by hand — run the script and commit the result.
> An item is only ✅ when a real test file exists and is listed.

Generated from: `backend/app/modules/settings/`

## P0 — Architecture Foundation

| Item | Status | Implementation | Test |
|---|---|---|---|
| Static registry (SettingDef for every key) | ✅ | `registry.py` | `test_settings_engine.py` |
| Scope hierarchy with DB-driven chain resolution | ✅ | `scope_graph.py` | `test_settings_engine_db.py` |
| Hierarchical resolver (chain → override → default) | ✅ | `service.py` | `test_settings_engine.py` |
| Value validation and coercion per type | ✅ | `registry.py` | `test_settings_engine.py` |
| Per-key write authorization | ✅ | `policy.py` | `test_settings_engine.py` |
| Audit trail (append-only history) | ✅ | `models.py` | `test_settings_engine.py` |
| Transactional outbox event on every write | ✅ | `events.py` | `test_settings_engine.py` |
| Rollback to a previous revision | ✅ | `service.py` | `test_settings_engine.py` |
| RLS on all tables | ✅ | `migrations/fe2026111801` | `test_settings_engine_db.py` |
| Optimistic concurrency (expected_history_id) | ✅ | `service.py` | `test_settings_engine.py` |
| Unique constraint NULLS NOT DISTINCT | ✅ | `migrations/fe2026111802` | `test_settings_engine_db.py` |

## P1 — Business Configuration

| Item | Status | Implementation | Test |
|---|---|---|---|
| Business profile settings | ✅ | `registry.py` | `test_settings_engine.py` |
| Business type & vertical | ✅ | `registry.py` | `test_settings_architecture.py` |
| POS / cashier settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Inventory settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Orders lifecycle settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Purchasing settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Catalog settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| E-invoice / ETA settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Print & receipt settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |
| Capabilities (vertical → owner switches) | ✅ | `capabilities.py` | `test_settings_architecture.py` |
| Presets (business-type configurations) | ✅ | `presets.py` | `test_apparel_ground_shop_preset.py` |
| Reports access control | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |

## P2 — Communication & Intelligence

| Item | Status | Implementation | Test |
|---|---|---|---|
| Customer AI agent settings | ✅ | `registry.py` | `test_settings_engine.py` |
| Analytics AI agent settings | ✅ | `registry.py` | `test_settings_engine.py` |
| Organization settings (multi-branch, language, brand) | ✅ | `registry.py` | `test_settings_architecture.py` |
| Branch operational settings | ✅ | `registry.py` | `test_settings_pos_purchasing_wiring.py` |

## P3 — Platform Management

| Item | Status | Implementation | Test |
|---|---|---|---|
| Team settings (default_role, require_2fa, session_timeout) | ✅ | `registry.py` | `test_settings_remaining_wiring.py` |
| Security settings (passwords, API rotation, audit, IP) | ✅ | `registry.py` | `test_settings_remaining_wiring.py` |
| Notification settings | ✅ | `registry.py` | `test_settings_remaining_wiring.py` |
| Billing settings | ✅ | `registry.py` | `test_settings_remaining_wiring.py` |
| Frontend unified /settings/effective consumption | 🟡 | `frontend/src/` | — |

## P4 — Advanced Governance

| Item | Status | Implementation | Test |
|---|---|---|---|
| Change requests (approval-gated settings) | ✅ | `service.py` | `test_settings_final_wiring.py` |
| Change request lifecycle (draft → applied) | ✅ | `models.py` | `test_settings_final_wiring.py` |
| Config migration framework | ✅ | `config_migrations.py` | `test_config_migrations.py` |
| Tenant-scoped restore (§164) | ✅ | `service.py` | `test_tenant_restore.py` |
| SLO framework (§168) | ✅ | `slo.py` | `test_settings_slo.py` |
| Advanced/composable presets (§170) | ✅ | `presets.py` | `test_advanced_presets.py` |
| Advanced approvals — sensitive settings (§172) | ✅ | `service.py` | `test_advanced_approvals.py` |
| Extended auditing — source + filtered search (§174) | ✅ | `service.py` | `test_extended_auditing.py` |
| Compliance matrix (auto-generated, test-synced) | ✅ | `scripts/dev/gen_compliance_matrix.py` | `test_compliance_matrix_sync.py` |
| Dynamic presets (runtime creation) | ❌ | — | — |
| SecretStore integration for secret sensitivity | ✅ | `core/secrets.py` | `test_settings_remaining_wiring.py` |
| Guard test: enforced keys | ✅ | `registry.py` | `test_settings_enforced_keys.py` |
| Guard test: registry spec in sync | ✅ | `registry.py` | `test_registry_spec_in_sync.py` |

## Summary

| Status | Count |
|---|---|
| ✅ Done | 43 / 45 |
| 🟡 Partial | 1 / 45 |
| ❌ Missing | 1 / 45 |

