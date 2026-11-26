/** Both languages carry the same keys, and none of them is empty.
 *
 * This exists because the Settings Center shipped a page whose six labels were
 * referenced but never written: `t()` returns the key when it is missing, so the
 * panel rendered "settings.customers.templates.title" as a heading and every test
 * still passed. A key set that differs between ar and en is the cheapest possible
 * signal that something was half-added, and it costs nothing to check.
 */
import { describe, expect, test } from "vitest";
import ar from "./ar";
import en from "./en";

describe("i18n parity", () => {
  test("both languages carry exactly the same keys", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort());
  });

  test("no string is missing or blank in either language", () => {
    const blanks = [];
    for (const [lang, table] of [
      ["ar", ar],
      ["en", en],
    ]) {
      for (const [key, value] of Object.entries(table)) {
        if (typeof value !== "string" || value.trim() === "") blanks.push(`${lang}:${key}`);
      }
    }
    expect(blanks).toEqual([]);
  });

  test("the reply template labels the settings page reads are really written", () => {
    const keys = ["title", "desc", "empty", "loading", "loadError", "whereToEdit"];
    for (const lang of [ar, en]) {
      for (const k of keys) {
        const value = lang[`settings.customers.templates.${k}`];
        expect(typeof value).toBe("string");
        expect(value).not.toContain("settings.customers");
      }
    }
  });
});
