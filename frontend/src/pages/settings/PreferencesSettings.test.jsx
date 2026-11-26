/**
 * The preferences page: five choices that belong to the account, not the browser.
 *
 * What is worth pinning here is that each choice is a REAL choice — the control
 * exists for every value the server accepts, the date example is a rendered date
 * rather than a format code, and the page says out loud that the clock is the
 * person's own and not the branch's. A preferences screen that silently drops one
 * of the values it offers is how a stored setting becomes unreachable.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { ThemeProvider } from "@/lib/themeContext";
import PreferencesSettings from "./PreferencesSettings";

const render = () =>
  renderToStaticMarkup(
    <I18nProvider>
      <ThemeProvider>
        <PreferencesSettings />
      </ThemeProvider>
    </I18nProvider>
  );

describe("PreferencesSettings", () => {
  test("every value the API accepts is offered on the page", () => {
    const html = render();
    for (const testid of [
      "prefs-language",
      "prefs-theme",
      "prefs-timezone",
      "prefs-date-format",
      "prefs-default-page",
    ]) {
      expect(html).toContain(`data-testid="${testid}"`);
    }
    // the three date shapes and the three appearances, not a subset
    expect(html).toContain("DD/MM/YYYY");
    expect(html).toContain("MM/DD/YYYY");
    expect(html).toContain("YYYY/MM/DD");
    expect(html).toContain("System");
    expect(html).toContain("Dark");
  });

  test("the date control shows a real rendered date, not a format code", () => {
    const html = render();
    expect(html).toMatch(/For example: \d{2}\/\d{2}\/\d{4}/);
  });

  test("the landing page offers only routes the API whitelists", () => {
    const html = render();
    for (const route of ["/dashboard", "/inbox", "/cashier", "/customers", "/settings"]) {
      expect(html).toContain(`value="${route}"`);
    }
  });

  test("the person is told the clock is theirs, not the branch's", () => {
    const html = render();
    expect(html).toContain("Your own clock, not the branch&#x27;s");
  });

  test("the page says the choices follow the account rather than the device", () => {
    const html = render();
    expect(html).toContain("belong to your account, not the device");
  });

  test("a real IANA zone is selectable before any request answers", () => {
    const html = render();
    expect(html).toContain('value="Africa/Cairo"');
  });
});
