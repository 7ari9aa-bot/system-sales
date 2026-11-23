import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ChannelContactDrawer from "./ChannelContactDrawer";

const render = (messages = []) =>
  renderToStaticMarkup(
    React.createElement(ChannelContactDrawer, {
      isOpen: true,
      onClose() {},
      channel: { id: "messenger", name: "Messenger" },
      conversation: { id: "c1", customer: "Ahmed Adel", channel: "messenger", messages },
      lang: "ar",
    }),
  );

describe("the Messenger details panel", () => {
  test("shows the person, the profile and search actions and the folded sections", () => {
    const html = render();
    expect(html).toContain('data-testid="messenger-details"');
    expect(html).toContain("Ahmed Adel");
    expect(html).toContain('data-testid="messenger-action-profile"');
    expect(html).toContain('data-testid="messenger-action-search"');
    expect(html).toContain('data-testid="messenger-section-media"');
  });

  test("invents nothing: no phone number, no mute, no encryption claim", () => {
    const html = render();
    expect(html).not.toContain("+20 101");
    expect(html).not.toContain("كتم");
    expect(html).not.toContain("مشفر");
  });
});
