import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

let data = { lang: "en", canAct: true };
vi.mock("./useFacebookData", () => ({ useFacebookData: () => data }));
import FacebookInsightsPage from "./FacebookInsightsPage";

const day = (n, value) => ({ value, end_time: `2026-11-0${n}T08:00:00+0000` });
const metrics = [
  { name: "page_follows", values: [day(1, 100), day(2, 104), day(3, 110)] },
  { name: "page_media_view", values: [day(1, 5), day(2, 9), day(3, 2)] },
  { name: "page_post_engagements", values: [] },
];
const html = (loaded = metrics) => {
  const client = new QueryClient();
  if (loaded) client.setQueryData(["facebook-insights"], loaded);
  return renderToStaticMarkup(<QueryClientProvider client={client}><FacebookInsightsPage /></QueryClientProvider>);
};

describe("the Insights page", () => {
  it("shows a card per metric: followers as they are now, views as a total", () => {
    data = { lang: "en", canAct: true };
    const out = html();
    expect(out).toContain("Followers");
    expect(out).toContain(">110<");
    expect(out).toContain("Content views");
    expect(out).toContain(">16<");
  });
  it("draws a daily chart under each metric that has days, and none for one without", () => {
    data = { lang: "en", canAct: true };
    const out = html();
    expect((out.match(/role="img"/g) || []).length).toBe(2);
    expect(out).toContain("2026-11-02: 9");
  });
  it("shows a dash, not a zero, for a metric Meta sent no days for", () => {
    data = { lang: "en", canAct: true };
    expect(html()).toContain(">—<");
  });
  it("on the demo account says there is no Page and draws nothing", () => {
    data = { lang: "en", canAct: false };
    const out = html(null);
    expect(out).not.toContain('role="img"');
  });
  it("speaks Arabic", () => {
    data = { lang: "ar", canAct: true };
    const out = html();
    expect(out).toContain("الإحصاءات");
    expect(out).toContain("المتابعون");
  });
});
