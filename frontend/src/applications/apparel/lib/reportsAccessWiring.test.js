import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { REPORTS_ACCESS_KEYS } from "@/applications/apparel/components/settings/ReportsAccessSettings";

// Whether a manager sees cost and profit is the shop owner's call, kept on the server. The screen
// is JSX the test setup cannot render, so the links are guarded at the source: a broken one leaves
// the owner with a setting no screen can change.
// The application tree moved under src/applications/apparel, one level deeper than
// it used to sit. A helper path is written either from the application root or
// from src, so resolve against both instead of guessing which one this file meant.
const read = (rel) => {
  for (const base of ["../../../../", "../../../", "../../"]) {
    try {
      return readFileSync(new URL(base + rel, import.meta.url), "utf8");
    } catch {
      // try the next base
    }
  }
  throw new Error(`cannot resolve ${rel}`);
};
const screen = read("apparel/components/settings/ReportsAccessSettings.jsx");
const settingsPage = read("pages/settings/PosSettings.jsx");
const registry = readFileSync(new URL("../../../../../backend/app/platform/settings/registry.py", import.meta.url), "utf8");

describe("the owner's switch for who sees cost and profit", () => {
  it("asks for exactly the key the server registers, in the business domain", () => {
    expect(REPORTS_ACCESS_KEYS).toEqual(["reports.managers_see_profit"]);
    expect(registry).toContain('key="reports.managers_see_profit"');
    expect(screen).toMatch(/domain="business"/);
    expect(screen).toMatch(/keys=\{REPORTS_ACCESS_KEYS\}/);
  });

  it("is a setting the server enforces, so the settings engine will list it", () => {
    const enforced = registry.slice(registry.indexOf("ENFORCED_KEYS"));
    expect(enforced).toContain('"reports.managers_see_profit"');
  });

  it("is on the settings page, in the tab where the owner decides who sees what", () => {
    expect(settingsPage).toMatch(/import ReportsAccessSettings from "@\/applications\/apparel\/components\/settings\/ReportsAccessSettings"/);
    expect(settingsPage).toMatch(/value: "users"/);
    expect(settingsPage).toMatch(/<ReportsAccessSettings \/>/);
  });

  it("does not hide the existing users screen", () => {
    expect(settingsPage).toMatch(/<UsersSettings \/>/);
  });

  it("tells the owner the cashier never sees it, whatever the switch says", () => {
    expect(screen).toMatch(/الكاشير لا يراه أبدًا/);
  });
});
