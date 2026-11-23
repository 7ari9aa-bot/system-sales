import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import MessengerRowText from "./MessengerRowText";

const render = (conversation, lang = "ar") => renderToStaticMarkup(React.createElement(MessengerRowText, { conversation, lang }));
const base = { customer: "Ahmed Adel", preview: "تمام", time: "01:46", unread: 0, lastDirection: "inbound" };

describe("a Messenger list row", () => {
  test("shows the name, the preview and the time", () => {
    const html = render(base);
    expect(html).toContain("Ahmed Adel");
    expect(html).toContain("تمام");
    expect(html).toContain("01:46");
  });

  test("says 'You:' when the newest message is ours", () => {
    expect(render({ ...base, lastDirection: "outbound" })).toContain("أنت: تمام");
  });

  test("an unread row has a blue dot and a bold name; a read one has neither", () => {
    expect(render({ ...base, unread: 2 })).toContain('data-testid="messenger-unread-dot"');
    expect(render({ ...base, unread: 2 })).toContain("font-semibold");
    expect(render(base)).not.toContain('data-testid="messenger-unread-dot"');
  });

  test("draws no status chip and no unread count", () => {
    const html = render({ ...base, unread: 2, status: "waiting" });
    expect(html).not.toContain(">2<");
  });
});
