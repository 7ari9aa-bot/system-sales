/**
 * The strip that tells the owner the truth about the link to their own phone app.
 *
 * Coexistence's promise is that the WhatsApp Business app keeps working while FIHRIST mirrors it.
 * Two failures break that promise silently: Meta removed the partner (nothing sends any more) and
 * the history sync stopped. The banner is the only place a person sees either from the inbox, so
 * each state gets its own tone, its own sentence and, where it helps, a way back to settings.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";
import CoexistenceBanner, { syncProgress } from "./CoexistenceBanner";
import { isSettled } from "@/hooks/useCoexistenceStatus";

const status = (extra = {}) => ({
  connected: true,
  sync_state: "HISTORY_SYNC_IN_PROGRESS",
  sync_label: { en: "Importing your chat history", ar: "بنجيب سجل المحادثات" },
  ready: false,
  offboarded: false,
  contacts: { sync_type: "contacts", state: "completed", progress: 100, messages_stored: 42 },
  history: { sync_type: "history", state: "in_progress", progress: 60, messages_stored: 128 },
  ...extra,
});

const render = (props) =>
  renderToStaticMarkup(
    React.createElement(MemoryRouter, null, React.createElement(CoexistenceBanner, { lang: "en", ...props })),
  );

describe("CoexistenceBanner", () => {
  test("shows the running half of the sync with its real percentage and count", () => {
    const html = render({ status: status() });
    expect(html).toContain('data-tone="syncing"');
    expect(html).toContain("Importing your chat history");
    expect(html).toContain("60%");
    expect(html).toContain("128");
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="60"');
  });

  test("says nothing once everything is synced", () => {
    expect(render({ status: status({ ready: true, sync_state: "READY" }) })).toBe("");
  });

  test("a removed number says it is disconnected, with Meta's reason and a way back", () => {
    const html = render({
      status: status({ connected: false, offboarded: true, sync_state: "OFFBOARDED", disconnect_event: "PARTNER_REMOVED", disconnect_reason: "partner_removed" }),
    });
    expect(html).toContain('data-tone="disconnected"');
    expect(html).toContain("not connected");
    expect(html).toContain("partner_removed");
    expect(html).toContain('href="/settings/channels"');
    // A dead channel must not also show a cheerful progress bar.
    expect(html).not.toContain('role="progressbar"');
  });

  test("a declined history is stated as a choice, not as a failure", () => {
    const html = render({ status: status({ sync_state: "HISTORY_NOT_SHARED", history: { sync_type: "history", state: "not_shared", progress: 0, messages_stored: 0 } }) });
    expect(html).toContain('data-tone="not-shared"');
    expect(html).toContain("chose not to share");
    expect(html).not.toContain('data-tone="failed"');
  });

  test("a stopped sync asks for a re-link instead of spinning forever", () => {
    const html = render({ status: status({ sync_state: "SYNC_FAILED" }) });
    expect(html).toContain('data-tone="failed"');
    expect(html).toContain("/settings/channels");
  });

  test("a failed status read hides the strip rather than breaking the thread", () => {
    expect(render({ status: null })).toBe("");
  });

  test("speaks Arabic when the inbox does", () => {
    expect(render({ status: status(), lang: "ar" })).toContain("بنجيب سجل المحادثات");
  });
});

describe("syncProgress", () => {
  test("the running half wins over a finished one", () => {
    expect(syncProgress(status()).kind).toBe("history");
    expect(syncProgress(status()).percent).toBe(60);
  });

  test("no runs at all means no bar", () => {
    expect(syncProgress(status({ contacts: null, history: null }))).toBeNull();
  });

  test("a percentage from Meta is clamped to a bar", () => {
    expect(syncProgress(status({ history: { sync_type: "history", state: "in_progress", progress: 180 } })).percent).toBe(100);
  });
});

describe("isSettled", () => {
  test("stops polling when nothing more can arrive", () => {
    expect(isSettled(status())).toBe(false);
    expect(isSettled(status({ ready: true }))).toBe(true);
    expect(isSettled(status({ offboarded: true }))).toBe(true);
    expect(isSettled(status({ sync_state: "SYNC_FAILED" }))).toBe(true);
    expect(isSettled(status({ sync_state: "HISTORY_NOT_SHARED" }))).toBe(true);
    expect(isSettled(null)).toBe(false);
  });
});
