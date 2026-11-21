import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import FacebookMessagesRedirect, { MESSENGER_INBOX } from "./FacebookMessagesRedirect";

describe("old /facebook/messages links", () => {
  it("point at the inbox with the Messenger channel selected", () => {
    expect(MESSENGER_INBOX).toBe("/inbox?channel=messenger");
  });
  it("render a redirect element, not the old page", () => {
    const out = renderToStaticMarkup(<MemoryRouter><FacebookMessagesRedirect /></MemoryRouter>);
    expect(out).toBe("");
  });
});
