import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import * as icons from "./icons";

const components = Object.entries(icons).filter(([, value]) => typeof value === "function");

describe("whatsapp icons", () => {
  test("the set is complete", () => {
    expect(components.length).toBeGreaterThanOrEqual(18);
  });

  test.each(components)("%s renders real, decorative-by-default svg geometry", (name, Icon) => {
    const html = renderToStaticMarkup(React.createElement(Icon, {}));
    expect(html).toMatch(/<svg/);
    expect(html).toMatch(/<(path|circle|rect)/);
    expect(html).not.toMatch(/NaN|undefined/);
    // A stray "1.500"-style number is how a mis-typed path slips in.
    expect(html).not.toMatch(/\d\.\d*00["\s]/);
    // Purely decorative unless the caller names it.
    expect(html).toMatch(/aria-hidden="true"/);
  });

  test("the channel badge can carry an accessible name", () => {
    const html = renderToStaticMarkup(React.createElement(icons.WhatsAppChannelBadge, { title: "WhatsApp" }));
    expect(html).toMatch(/role="img"/);
    expect(html).toMatch(/aria-label="WhatsApp"/);
    expect(html).not.toMatch(/aria-hidden/);
  });
});
