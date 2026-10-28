# Documentation index / فهرس الوثائق

Start here. Files are grouped by what they are for, not by when they were written.
**Status** says whether a file describes the system as it is (`live`), a decision record that
still binds (`decision`), or a snapshot of a moment that has passed (`history`).

> **Never put a credential in this folder.** The repository is public.
> `backend/tests/test_no_committed_secrets.py` fails CI if one is committed.
> Tokens and keys live in Railway variables / the secret store only.

## 1. Read first

| File | What it is | Status |
|---|---|---|
| [../AGENTS.md](../AGENTS.md) | Start here: map of the repository, the rules, how to run it. Also read [../backend/AGENTS.md](../backend/AGENTS.md) for backend work. | live |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The canonical architecture. | live |
| [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md) | Module-by-module map (Arabic/English). | live |
| [AGENT_BRIEF.md](AGENT_BRIEF.md) | Rules for anyone (human or AI) changing the code. | live |
| [RUNBOOK.md](RUNBOOK.md) | Operating the system in production. | live |

## 2. Decisions (ADRs): two numbering systems

`ADR-013` alone names **two different documents**. Always use the prefix.
[ADRS.md](ADRS.md) is the single index for both.

| Folder | Cite as | Contents |
|---|---|---|
| [adr/](adr/) | `SPEC ADR-0NN` | The baseline ADRs bundled with the spec (001 to 041). |
| [adrs/](adrs/) | `ADR-0NN` / `D16` | This project's own decision records, one file per decision. |

## 3. Product areas

| Area | Files |
|---|---|
| Channels (WhatsApp, Instagram, Messenger, Telegram, web chat) | [CHANNELS.md](CHANNELS.md), [META_SETUP.md](META_SETUP.md), [channels/](channels/) |
| Cashier / POS | [POS_IMPLEMENTATION_PLAN.md](POS_IMPLEMENTATION_PLAN.md), [POS_EXPANSION_PLAN.md](POS_EXPANSION_PLAN.md), [POS_ERPNEXT_STUDY.md](POS_ERPNEXT_STUDY.md), [COMMERCE_CORE_ARCHITECTURE.md](COMMERCE_CORE_ARCHITECTURE.md) |
| Customer AI agent | [design/](design/) (core design, M1 handoff, red team) |
| Desktop app | [DESKTOP_ARCH_REVIEW.md](DESKTOP_ARCH_REVIEW.md), and `desktop/docs/` in the repo root |

## 4. Operations and platform

| File | What it is | Status |
|---|---|---|
| [SUPABASE_RUNTIME.md](SUPABASE_RUNTIME.md) | What Supabase is responsible for at runtime. | live |
| [ACCOUNT_RECOVERY.md](ACCOUNT_RECOVERY.md) | Account-recovery email setup. | live |
| [RAILWAY_TOKEN_GUIDE.md](RAILWAY_TOKEN_GUIDE.md), [RAILWAY_ACCOUNT_TOKEN_GUIDE.md](RAILWAY_ACCOUNT_TOKEN_GUIDE.md) | How to call the Railway API. Describe the calls only; the token itself is never written down. | live |
| [platform-reviews/](platform-reviews/) | Per-platform review notes (GitHub, Railway, Supabase, Vercel) and manual steps. | live |

## 5. Governance and audit

| File | What it is | Status |
|---|---|---|
| [COMPLIANCE_MATRIX.md](COMPLIANCE_MATRIX.md) | Spec sections mapped to code. | live |
| [PII_DATA_MAP.md](PII_DATA_MAP.md) | Personal-data lifecycle. | live |
| [RISK_REGISTER.md](RISK_REGISTER.md) | Known risks. | live |
| [GAP_REGISTER.md](GAP_REGISTER.md) | Full-system critique audit. | live |
| [CONTRACT_AUDIT.md](CONTRACT_AUDIT.md) | "Defined, then bypassed" audit. | history |
| [ROADMAP_TO_90.md](ROADMAP_TO_90.md), [PATH_BREAKDOWN.md](PATH_BREAKDOWN.md) | Plan and work-package split. | history |

## 6. Status reports (snapshots)

Kept for context. They describe a moment, not the current system: [reports/](reports/).

## 7. Spec and archive

| Folder | Contents |
|---|---|
| [spec/](spec/) | The original architecture spec and its patches. |
| [archive/](archive/) | Superseded plans. Do not follow them; see [archive/README.md](archive/README.md). |
| [reviews/](reviews/) | Review notes from earlier waves. |
| [superpowers/](superpowers/) | Implementation plans. |
