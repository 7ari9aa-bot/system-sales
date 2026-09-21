# ADR-032: Canonical Message Model

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §155

## Problem
Each channel (WhatsApp, Telegram, Webchat) had different message shapes. Cross-channel features (search, AI context, customer timeline) needed to normalize each time.

## Decision
Channel normalization transforms all inbound messages into a canonical model: text, media, voice, image, video, file, location, contact, buttons, list, reaction, reply_to, edited, deleted, provider_metadata. Unsupported content is marked UNSUPPORTED_CONTENT with raw metadata preserved.

## Alternatives
- Store raw only (rejected: every consumer needs to normalize)
- Per-channel message tables (rejected: breaks customer 360)

## Rationale
§155: "Channel normalization transforms into a canonical model."

## Consequences
- The canonical model is the storage format; raw is kept as metadata
- New channels only need to implement normalization to the canonical model
