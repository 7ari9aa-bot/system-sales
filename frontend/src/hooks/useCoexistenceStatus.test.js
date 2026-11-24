/**
 * A status read that is not a status must not be drawn.
 *
 * The inbox asks for the channel state on every open. When that read came back as a fallback
 * (an empty array from a proxy or an error handler) the hook kept it as if it were the channel, so
 * the banner drew a "syncing" strip with no numbers — and pushed the chat wallpaper out of place.
 */
import { describe, expect, test } from "vitest";
import { isSettled, normalizeStatus } from "./useCoexistenceStatus";

describe("normalizeStatus", () => {
  test("keeps a real status object", () => {
    const status = { connected: true, sync_state: "READY", ready: true };
    expect(normalizeStatus(status)).toBe(status);
  });

  test("rejects the shapes a failed read produces", () => {
    expect(normalizeStatus([])).toBeNull();
    expect(normalizeStatus(null)).toBeNull();
    expect(normalizeStatus(undefined)).toBeNull();
    expect(normalizeStatus("ok")).toBeNull();
    expect(normalizeStatus(0)).toBeNull();
  });

  test("an empty channel is still a channel", () => {
    // {} is what the endpoint returns for a workspace with no WhatsApp link: not an error.
    expect(normalizeStatus({})).toEqual({});
  });
});

describe("isSettled", () => {
  test("nothing to wait for once ready, offboarded, failed or declined", () => {
    expect(isSettled({ ready: true })).toBe(true);
    expect(isSettled({ offboarded: true })).toBe(true);
    expect(isSettled({ sync_state: "SYNC_FAILED" })).toBe(true);
    expect(isSettled({ sync_state: "HISTORY_NOT_SHARED" })).toBe(true);
    expect(isSettled({ sync_state: "HISTORY_SYNC_IN_PROGRESS" })).toBe(false);
    expect(isSettled(null)).toBe(false);
  });
});
