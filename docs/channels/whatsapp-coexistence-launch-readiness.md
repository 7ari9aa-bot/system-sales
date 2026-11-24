# WhatsApp Coexistence: what the launch-blocker report asked for, and where it stands

Branch `fix/whatsapp-coexistence-launch-blockers` (PR #93). One row per report item, with the
commit that closes it and the evidence that it is closed. Read the "still needs a real number"
section before calling this launched: two of these can only be finished on a real Meta Business
App number.

| # | Report item | Commit | Evidence |
|---|---|---|---|
| 1.1 | `POST /integrations/connect` accepted `whatsapp` | `bc45dfb` | Route refuses before Meta; dead token form removed; tests |
| 1.2 | Echo of an already-imported message skipped the human handover | `aa9b358` | Handover guaranteed per echo, failure fails the batch; 4 tests |
| 1.3 | Durable reservation untested; channel not committed before Meta | `e9d5f5f` | 4 Postgres tests + `_start_coexistence_sync` commits first |
| 1.4 | `record_chunk` trusted any chunk | `a4817ef` | `attribute_chunk` gates on tenant/number/type/epoch/request id |
| 2.1 | First contacts webhook treated as a finished list | `42b97e7` | Snapshot ≠ completion; `settled_by: deadline` |
| 2.2 | History preferred BSUID, live preferred phone | `e18f7c4` | Phone primary, BSUID alias, everywhere; direction fixed |
| 2.3 | Remove-before-add could resurrect a contact | `5e0dc00` | `whatsapp_contact_tombstones` + migration `fe2026112402` |
| 2.4 | Multiple `history[]` elements merged | `0f53e57` | One batch per element, own progress and dedupe key |
| 2.5 | `reply_to_message_id` dropped on import | `3d744ce` | Resolved locally, provider id kept when absent |
| 2.6 | 131060 notice invisible in an open thread | `7d48ba1` | Outbox event + unread counter, AI skips it |
| 2.7 | Stuck `dispatching` had no diagnostics | `2b6dc6e` | `needs_attention`, request id, age, reconcile without a second send |
| 3.1 | Settings showed link-time state only | `85482e7` | `WhatsAppSyncCard` reads the live status |
| 3.2 | No rate-limit indicator | `85482e7` | `throughput` on the status endpoint, 130429 explained |
| 3.3 | No merchant-facing limits page | `22c2afd`, `85482e7` | `whatsapp-coexistence-limits.md` + in-app copy, pinned |
| 3.4 | Docs contradicted READY | `22c2afd` | Guide states the real condition, pinned by a test |
| 4 | Test matrix | `e9d5f5f`, `65e612d` | Automated cases in CI + the manual end-to-end checklist |
| - | Vercel failing on the PR | none needed | Rate limited, not code: see below |

## Vercel

Not a code failure. Every commit after `0f53e57` carries the Vercel status "Deployment rate limited
— retry in 24 hours", and Vercel created no deployment for them. The last commit it did attempt,
`0f53e57`, built and deployed READY. The project's 60 most recent deployments contain no ERROR
state. The fix is time (the quota window) or a plan change, not a patch.

## The four test files that carry the report

* `tests/test_whatsapp_sync_durable_pg.py` — the one-shot reservation on Postgres: committed before
  Meta, survives a crash, one of two concurrent requests sends nothing, RLS holds.
* `tests/test_whatsapp_coexistence_import.py` — history/echo/contact import, attribution, replies,
  identity, tombstones.
* `tests/test_whatsapp_coexistence_status.py` — the states, the READY condition, the stuck run and
  the reconcile path.
* `tests/test_whatsapp_coexistence_doc_pins_the_ready_condition.py` and
  `tests/test_whatsapp_coexistence_limits_doc.py` — the docs cannot drift from the code again.

## Still needs a real Meta Business App number

1. **Meta's real webhook order and payloads** for history and contacts on a live link. Fixtures
   encode what the docs say; only a real number proves the order we tolerate is the order Meta
   sends. Run `docs/channels/whatsapp-coexistence-manual-check.md`.
2. **Devices Meta does not support** (WhatsApp for Windows, WearOS) and the 131060 notice they
   produce: documented from Meta's docs, not observed.
3. **The 24-hour window closing** on a real connection: our deadline path is tested with a clock,
   not with Meta.
4. **Removal by Meta** (`PARTNER_REMOVED`) on a live partner: the routing is tested from a payload,
   the real event has not been seen.
