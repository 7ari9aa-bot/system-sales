/**
 * A save names the revision every key was read at, including "never written".
 *
 * `expected_history_ids` used to carry only the keys that already had a revision, so the
 * first write of a fresh setting travelled with no expectation at all: two users editing
 * a never-saved setting both passed, and the second silently overwrote the first instead
 * of getting a 409. A key pinned to null now means "I expect no revision".
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, "useSettings.js"), "utf8");

describe("useSettings expected revisions", () => {
  it("pins every saved key, using null when it has no revision", () => {
    expect(source).toContain("expectedIds[k] = historyIds[k] ?? null");
  });

  it("no longer skips the keys without a history id", () => {
    expect(source).not.toContain("if (historyIds[k]) expectedIds[k] = historyIds[k]");
  });
});
