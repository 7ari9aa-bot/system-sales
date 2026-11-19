import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

let data = { lang: "en", canAct: false };
vi.mock("./useFacebookData", () => ({ useFacebookData: () => data }));
import FacebookReelsPage from "./FacebookReelsPage";

const html = () => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><FacebookReelsPage /></QueryClientProvider>);

describe("the Reels and Stories page", () => {
  it("on the demo account says there is no Page and offers no publish button", () => {
    data = { lang: "en", canAct: false };
    const out = html();
    expect(out).toContain("no connected Facebook Page");
    expect(out).not.toContain("New reel");
    expect(out).not.toContain("New story");
  });
  it("on a real account has both tabs and a publish button, and starts on Reels", () => {
    data = { lang: "en", canAct: true };
    const out = html();
    expect(out).toContain('role="tablist"');
    expect(out).toMatch(/aria-selected="true"[^>]*>Reels</);
    expect(out).toContain("New reel");
    expect(out).not.toContain("New story");
  });
  it("speaks Arabic", () => {
    data = { lang: "ar", canAct: true };
    const out = html();
    expect(out).toContain("الريلز والستوري");
    expect(out).toContain("ريل جديد");
  });
});
