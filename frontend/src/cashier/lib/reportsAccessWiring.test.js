import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { REPORTS_ACCESS_KEYS } from "@/cashier/components/settings/ReportsAccessSettings";

// Whether a manager sees cost and profit is the shop owner's call, kept on the server. The screen
// is JSX the test setup cannot render, so the links are guarded at the source: a broken one leaves
// the owner with a setting no screen can change.
const read = (rel) => readFileSync(new URL(`../../${rel}`, import.meta.url), "utf8");
const screen = read("cashier/components/settings/ReportsAccessSettings.jsx");
const settingsPage = read("pages/settings/PosSettings.jsx");
const registry = readFileSync(new URL("../../../../backend/app/modules/settings/registry.py", import.meta.url), "utf8");

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
    expect(settingsPage).toMatch(/import ReportsAccessSettings from "@\/cashier\/components\/settings\/ReportsAccessSettings"/);
    expect(settingsPage).toMatch(/<TabsContent value="users"[^>]*><UsersSettings \/><ReportsAccessSettings \/><\/TabsContent>/);
  });

  it("does not hide the existing users screen", () => {
    expect(settingsPage).toMatch(/<UsersSettings \/>/);
  });

  it("tells the owner the cashier never sees it, whatever the switch says", () => {
    expect(screen).toMatch(/الكاشير لا يراه أبدًا/);
  });
});
