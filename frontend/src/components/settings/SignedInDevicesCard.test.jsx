/**
 * The signed-in devices card: the one screen a person uses while deciding whether their account
 * has been opened somewhere they did not open it.
 *
 * The assertions that matter are the negative ones. An unread list must not look like "no other
 * devices", the device that asked must be identifiable, and the button that signs you out of
 * everything must never be the quiet one next to the safe one.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import SignedInDevicesCard from "./SignedInDevicesCard";

const render = (props) =>
  renderToStaticMarkup(
    <I18nProvider>
      <SignedInDevicesCard {...props} />
    </I18nProvider>
  );

// the whole opening tag of one button, so an assertion can speak about ITS attributes rather than
// about a class string that happens to contain the word "disabled"
const buttonTag = (html, testid) => {
  const at = html.indexOf(`data-testid="${testid}"`);
  if (at === -1) return "";
  return html.slice(html.lastIndexOf("<button", at), at);
};

const thisDevice = {
  id: "s1",
  device: "Chrome · Windows",
  ip: "203.0.113.7",
  signed_in_at: "2026-11-26T09:00:00+00:00",
  expires_at: "2026-12-10T09:00:00+00:00",
  current: true,
};

const otherDevice = {
  id: "s2",
  device: "Safari · iPhone",
  ip: "198.51.100.9",
  signed_in_at: "2026-11-25T18:30:00+00:00",
  expires_at: "2026-12-09T18:30:00+00:00",
  current: false,
};

describe("SignedInDevicesCard", () => {
  test("an unread list says so instead of implying there are no other devices", () => {
    const html = render({ devices: null });
    expect(html).toContain('data-testid="devices-loading"');
    expect(html).not.toContain('data-testid="devices-empty"');
    expect(html).not.toContain('data-testid="devices-list"');
  });

  test("a genuinely empty list is its own, different message", () => {
    const html = render({ devices: [] });
    expect(html).toContain('data-testid="devices-empty"');
    expect(html).not.toContain('data-testid="devices-loading"');
  });

  test("the asking device is marked and cannot be signed out from its own row", () => {
    const html = render({ devices: [thisDevice, otherDevice] });
    expect(html).toContain("Chrome · Windows");
    expect(html).toContain("Safari · iPhone");
    expect(html).toContain("This device");
    // the current row offers no revoke button; the other one does
    expect(html).not.toContain('data-testid="device-revoke-s1"');
    expect(html).toContain('data-testid="device-revoke-s2"');
  });

  test("the IP is shown as the server sent it, in its own direction", () => {
    const html = render({ devices: [otherDevice] });
    expect(html).toContain("198.51.100.9");
    expect(html).toContain('dir="ltr"');
  });

  test("with no other devices the bulk action is disabled, not hidden", () => {
    const html = render({ devices: [thisDevice] });
    const tag = buttonTag(html, "devices-revoke-others");
    expect(tag).not.toBe("");
    expect(tag).toContain('disabled=""');
  });

  test("signing out everywhere carries its own warning and is not the outline button", () => {
    const html = render({ devices: [thisDevice, otherDevice] });
    expect(html).toContain("This signs you out too.");
    expect(buttonTag(html, "devices-revoke-all")).toContain("bg-destructive");
  });

  test("a failure from the server is spoken, and the list is not silently emptied", () => {
    const html = render({ devices: [thisDevice], error: "The sessions could not be read or closed." });
    expect(html).toContain('role="alert"');
    expect(html).toContain("The sessions could not be read or closed.");
  });
});
