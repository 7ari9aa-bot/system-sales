/**
 * The live half of the WhatsApp channel card.
 *
 * Settings used to show only the sync state captured at link time, so a merchant saw "about to
 * sync" for the whole transfer, never saw a reservation Meta never answered, and had no way to tell
 * a 130429 caused by our own send rate from a real failure. Each of those is asserted here.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import WhatsAppSyncCard from "./WhatsAppSyncCard";

const status = (extra = {}) => ({
  connected: true,
  sync_state: "HISTORY_SYNC_IN_PROGRESS",
  sync_label: { en: "Importing your chat history", ar: "بنجيب سجل المحادثات" },
  ready: false,
  offboarded: false,
  needs_attention: false,
  contacts: {
    sync_type: "contacts",
    state: "in_progress",
    progress: 0,
    messages_stored: 0,
    snapshot_received_at: "2026-11-24T09:00:00+00:00",
    settled_by: null,
  },
  history: { sync_type: "history", state: "in_progress", progress: 42, messages_stored: 310 },
  throughput: {
    limit_per_second: 20,
    window_seconds: 1,
    current: 3,
    remaining: 17,
    headroom_percent: 85,
    state: "ok",
    explains_130429: "Error 130429 means this number sent more than 20 messages in one second.",
  },
  ...extra,
});

const render = (props) => renderToStaticMarkup(<WhatsAppSyncCard lang="en" {...props} />);

describe("WhatsAppSyncCard", () => {
  test("renders the live state and both halves with their real progress", () => {
    const html = render({ status: status() });
    expect(html).toContain('data-state="HISTORY_SYNC_IN_PROGRESS"');
    expect(html).toContain("Importing your chat history");
    expect(html).toContain('data-testid="sync-run-contacts"');
    expect(html).toContain('data-testid="sync-run-history"');
    expect(html).toContain("42%");
    expect(html).toContain("310");
  });

  test("says the first contact batch arrived without calling the list complete", () => {
    const html = render({ status: status() });
    expect(html).toContain("The first contact batch arrived");
    expect(html).not.toContain("Contacts complete");
  });

  test("says when the 24h window closed instead of implying a full list", () => {
    const html = render({
      status: status({
        contacts: {
          sync_type: "contacts",
          state: "in_progress",
          progress: 0,
          messages_stored: 0,
          settled_by: "deadline",
        },
      }),
    });
    expect(html).toContain("The 24-hour window closed");
    expect(html).toContain("not the same as a complete list");
  });

  test("surfaces a stuck reservation with its request id and a local way to close it", () => {
    const html = render({
      status: status({
        needs_attention: true,
        history: {
          sync_type: "history",
          state: "dispatching",
          progress: 0,
          messages_stored: 0,
          needs_attention: true,
          attention: {
            reason: "Meta's answer never arrived.",
            request_id: "req-abc",
            reserved_at: "2026-11-24T09:00:00+00:00",
            age_seconds: 2400,
            last_error: null,
          },
        },
      }),
    });
    expect(html).toContain('data-testid="sync-attention"');
    expect(html).toContain("A sync request with no answer");
    expect(html).toContain("40 min");
    expect(html).toContain("req-abc");
    expect(html).toContain("Close it and ask for a re-link");
  });

  test("shows the send rate against the 20/s cap and explains 130429", () => {
    const html = render({ status: status() });
    expect(html).toContain('data-testid="whatsapp-throughput"');
    expect(html).toContain("3 of 20 msg/s");
    expect(html).toContain("Within the cap");
    expect(html).toContain("130429");
  });

  test("an at-cap number says a retry will succeed", () => {
    const html = render({
      status: status({
        throughput: {
          limit_per_second: 20,
          current: 20,
          remaining: 0,
          headroom_percent: 0,
          state: "at_cap",
        },
      }),
    });
    expect(html).toContain("at the cap. A retry will succeed");
  });

  test("an untracked number is not reported as an idle one", () => {
    const html = render({
      status: status({
        throughput: { limit_per_second: 20, current: null, state: "unknown" },
      }),
    });
    expect(html).toContain("not tracked right now");
  });

  test("a declined history is stated as a choice, not a failure", () => {
    const html = render({
      status: status({
        history: { sync_type: "history", state: "not_shared", progress: 0, messages_stored: 0 },
      }),
    });
    expect(html).toContain("chose not to share chat history");
  });

  test("renders nothing at all when there is no status", () => {
    expect(render({ status: null })).toBe("");
  });
});
