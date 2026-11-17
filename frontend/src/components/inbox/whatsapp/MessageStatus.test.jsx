import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import MessageStatus, { statusKind } from "./MessageStatus";

describe("statusKind", () => {
  test.each([
    ["read", "read"],
    ["delivered", "delivered"],
    ["sent", "sent"],
    ["failed", "failed"],
    ["queued", "queued"],
    ["READ", "read"],
  ])("%s -> %s", (input, expected) => expect(statusKind(input)).toBe(expected));

  test.each([[undefined], [null], [""], ["pending"], ["something-new"]])(
    "an unknown status (%s) is never shown as delivered",
    (input) => expect(statusKind(input)).toBe("queued"),
  );
});

describe("MessageStatus", () => {
  const render = (status, lang) => renderToStaticMarkup(React.createElement(MessageStatus, { status, lang }));

  test("read is blue, delivered is grey, and they are different", () => {
    expect(render("read")).toContain("#53bdeb");
    expect(render("delivered")).not.toContain("#53bdeb");
    expect(render("delivered")).toContain("#667781");
  });

  test("a failed message is red and announced as failed", () => {
    const html = render("failed", "ar");
    expect(html).toContain("#ea0038");
    expect(html).toContain("فشل الإرسال");
  });

  test("a queued message is not drawn as a tick", () => {
    const html = render("queued", "en");
    expect(html).toContain('data-status="queued"');
    expect(html).toContain("Sending");
  });
});
