# ADR-050: Inbound Voice Transcription Orchestration

- **Status:** Accepted
- **Date:** 2026-09-23
- **Spec:** §35–36 (voice: STT/TTS)
- **Related:** ADR-036 (memory governance — same "untrusted turn" principle), `docs/COMPLIANCE_MATRIX.md` §33–36

## Context

`conversations/voice.py` shipped a complete STT/TTS capability — providers,
protocols, budget-aware service — and then nothing called it. On the real
inbound path a WhatsApp voice note became an `Attachment` with
`transcription_status` NULL, no transcript anywhere queryable, and
`AgentRunner._conversation_history` skipped messages with an empty body. A
customer who spoke was answered as though they had said nothing.

Three things had to be decided at once: where the orchestration lives, where
the transcript text lives, and when the budget is charged. Each had a trap
already visible in the code:

- `VoiceService.transcribe` guarded `pending` as "another worker is
  mid-flight" — while the only writer of `pending` was going to be ingest
  meaning *queued*. Left as-is, the first real call would no-op forever.
- The transcript was meant to be stored via `transcript_id` pointing at a
  transcripts table that does not exist; the fallback was
  `hasattr(attachment, "transcript_text")` on a column that did not exist
  either — a transcription paid for and then dropped.
- §36 says STT is always behind the AI budget gate, and §42's gate API is
  reserve/settle. A check-then-call without a reservation lets two voice
  notes landing together overshoot the cap.

## Decision

### 1. The worker layer owns the orchestration

`transcribe_inbound_voice()` lives in `app/workers/message_worker.py`, not in
`conversations`. Two reasons, one architectural and one mechanical:

- It is the only code that must see both the attachment table and the AI
  budget gate. Putting that in `conversations` closes an import cycle
  (`conversations → ai → catalog → … → conversations`) and the module
  boundary ratchet exists precisely to refuse that trade.
- Ordering is a pipeline property, not a service property: the call runs
  inside `_on_received` under the conversation lease, **before**
  `maybe_auto_reply`, because the reply is built from history — a transcript
  that lands after the answer is a transcript nobody reads.

### 2. `pending` means queued; concurrency is a layer up

Ingest marks a durable audio object `transcription_status = "pending"` — that
IS the transcription job; nothing else queues one. `VoiceService.transcribe`
treats `pending` as the normal do-the-work state. The race the old guard
worried about is prevented where it actually occurs: the conversation lease
(§126) serializes per-conversation mutation and the ProcessedEvent inbox
(§127) dedupes event replays. Idempotency is still the status column — a
`completed` row returns its stored text, and the worker's
`WHERE transcription_status = 'pending'` select means no double reservation.

### 3. The transcript is a column on the Attachment

Migration `a7d0f4b2c6e9` adds `attachments.transcript_text`. The alternative
— a dedicated transcripts table keyed by `transcript_id` — is more normalized
and still open as a future move, but a transcript is metadata about one
attachment with exactly one producer; a whole table for one nullable text
column buys nothing until transcripts have their own lifecycle (segments,
confidence, multiple candidates). The read side goes through
`ConversationService.audio_transcripts()` (a read-model returning raw
columns) so the AI module never imports the attachment table and the
prompt-shaping decision stays on the AI side.

### 4. Budget reserved before the call; spend booked on outcome

`reserve_budget` runs before `VoiceService.transcribe`, `settle_reservation`
in a `finally`. A block (cap reached, fallback requested) marks the
attachment `failed` and returns — it is not an error: the customer's note is
already stored and delivered, and raising would retry and dead-letter a
healthy ingest. On success `record_usage` books the estimate so §42's cap
sees the money; provider failure also returns without raising (§36
best-effort — the note stays delivered, only the transcript is missing).

### 5. The context builder renders what it actually has

`_conversation_history` now emits, for a body-less inbound audio message,
either the transcript framed as what the customer said, or an explicit
"[customer sent a voice message; no transcript is available]" marker.
Silence and "we could not hear them" are different facts to a model, and
before this change both looked identical: nothing at all.

## Consequences

- A voice note on a tenant with no STT provider configured marks `failed`
  after one provider-lookup attempt — visible in data, invisible to the
  customer (the audio is still delivered to staff).
- TTS is still unwired (`synthesize`, `OpenAITTSProvider` have no caller).
  Auto voice reply is a product decision, not a wiring gap we are hiding —
  recorded in `docs/GAP_REGISTER.md` along with the related outbound gap
  (`_deliver_one` never passes `media_type`, so outbound audio would deliver
  as `image` once TTS exists).
- CI is the only venue that exercises this path (DB-backed tests skip
  without Postgres) — the `pending`-semantics bug above shipped red and was
  caught only there. The lesson is already encoded in
  `tests/test_no_expired_attribute_access.py`'s docstring: local green on a
  DB-skipping suite is not a claim.
