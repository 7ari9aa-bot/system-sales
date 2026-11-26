import { describe, expect, it } from "vitest";
import { normalizeSettingsPayload } from "./AnalyticsAgentCard";

// Regression: a definitions payload that was not a list threw while the AI screen was
// rendering, and the whole page was replaced by the error boundary — the dialect card below
// it, which had loaded fine, became unreachable.
describe("an analytics-agent payload the server should never send cannot take the screen down", () => {
  it("an object where a list was promised renders an empty card, not an exception", () => {
    const { defs, values } = normalizeSettingsPayload({ detail: "boom" }, {});
    expect(defs).toEqual([]);
    expect(values).toEqual({});
  });

  it("missing or null payloads are treated as empty", () => {
    expect(normalizeSettingsPayload(undefined, null)).toEqual({ defs: [], values: {} });
  });

  it("a real payload is passed through unchanged", () => {
    const { defs, values } = normalizeSettingsPayload(
      [{ key: "analytics_agent.enabled" }],
      { "analytics_agent.enabled": { value: true } },
    );
    expect(defs).toHaveLength(1);
    expect(values).toEqual({ "analytics_agent.enabled": true });
  });

  it("an effective entry with no resolved value does not throw", () => {
    expect(normalizeSettingsPayload([], { k: null }).values).toEqual({ k: undefined });
  });
});
