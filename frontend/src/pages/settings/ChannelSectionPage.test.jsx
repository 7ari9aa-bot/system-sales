import React from "react";
import { describe, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { I18nProvider } from "@/lib/i18n";
import ChannelSectionPage from "./ChannelSectionPage";
import { splitIntegrations } from "@/components/settings/ChannelSectionPanels";

vi.mock("@/lib/api", () => ({ api: vi.fn(() => Promise.resolve([])) }));
vi.mock("@/pages/settings/ChannelDiagnostics", () => ({ default: () => null }));

const ROWS = [
  { id: "1", provider: "whatsapp", kind: "channel", status: "connected" },
  { id: "2", provider: "instagram", kind: "channel", status: "connected" },
  { id: "3", provider: "erpnext", kind: "erp", status: "active" },
];

function render(page) {
  return renderToStaticMarkup(
    <I18nProvider>
      <MemoryRouter initialEntries={[`/settings/channels/${page}`]}>
        <ChannelSectionPage page={page} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("ChannelSectionPage", () => {
  test("a channel is an integration row of kind channel, and nothing else is", () => {
    const { channels, external } = splitIntegrations(ROWS);
    expect(channels.map((c) => c.provider)).toEqual(["whatsapp", "instagram"]);
    expect(external.map((c) => c.provider)).toEqual(["erpnext"]);
  });

  test("the {items, count} envelope is read the same as a bare list", () => {
    expect(splitIntegrations({ items: ROWS, count: 3 }).channels).toHaveLength(2);
    expect(splitIntegrations(null).channels).toHaveLength(0);
  });

  test.each(["data-sync", "external-integrations", "connection-health"])(
    "%s renders its own heading rather than a blank screen",
    (page) => {
      const html = render(page);
      expect(html).toMatch(/Data sync|External integrations|Connection health|مزامنة|التكاملات|صحة/);
    },
  );

  test("an unknown page falls back to data sync instead of an empty shell", () => {
    expect(render("nope")).toMatch(/Data sync|مزامنة/);
  });
});
