// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

/**
 * loadFacebookSdk rejects from script.onerror. That branch read `isAr`, which only exists inside the
 * component, so an ad blocker turned the friendly message into a ReferenceError.
 */
function stubBrowserWhereTheScriptFails() {
  const script = {};
  vi.stubGlobal("window", {});
  vi.stubGlobal("document", {
    createElement: () => script,
    body: { appendChild: () => script.onerror() },
  });
}

describe("loadFacebookSdk when the script cannot load", () => {
  it.each([
    [true, /Facebook SDK/],
    [false, /Could not load the Facebook SDK/],
  ])("rejects with a readable message (isAr=%s), not a ReferenceError", async (isAr, pattern) => {
    stubBrowserWhereTheScriptFails();
    const { loadFacebookSdk } = await import("./ChannelsSettings.jsx");
    const err = await loadFacebookSdk("app", "v26.0", isAr).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).not.toBe("ReferenceError");
    expect(err.message).toMatch(pattern);
  });
});
