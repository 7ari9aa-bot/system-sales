/**
 * The personal-notifications page: two real switches, one window, one clock.
 *
 * The page must not offer what the product cannot do. In-app is shown but locked
 * (the bell row is the record, not a preference), and the quiet window is stated in
 * the person's own zone — a window read in the wrong clock is a notification at
 * 03:00. Both of those are visible facts about the markup, so they are pinned here.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import NotificationPreferences from "./NotificationPreferences";

const render = () =>
  renderToStaticMarkup(
    <I18nProvider>
      <NotificationPreferences />
    </I18nProvider>
  );

describe("NotificationPreferences", () => {
  test("the three channels are rendered, with in-app locked", () => {
    const html = render();
    expect(html).toContain('data-testid="notif-in_app"');
    expect(html).toContain('data-testid="notif-email"');
    expect(html).toContain('data-testid="notif-push"');
    // in-app is the record of what happened: switchable would be a lie
    expect(html).toMatch(/data-testid="notif-in_app"[^>]*disabled/);
  });

  test("the quiet window is two real times, not a free-text field", () => {
    const html = render();
    expect(html).toContain('type="time"');
    expect(html).toContain('data-testid="notif-quiet-start"');
    expect(html).toContain('data-testid="notif-quiet-end"');
  });

  test("the page says which clock the window is read in", () => {
    const html = render();
    expect(html).toContain("The window is read in");
  });

  test("the page explains that in-app always arrives", () => {
    const html = render();
    expect(html).toContain("always recorded");
  });

  test("the quiet hours default is a real overnight window", () => {
    const html = render();
    expect(html).toContain('value="22:00"');
    expect(html).toContain('value="07:00"');
  });
});
