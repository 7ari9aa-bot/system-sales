import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { ModuleLinkPage } from "@/components/settings/ModuleLinkPage";
import { allPageLinks, pageLink, sectionBySlug } from "@/components/settings/settingsManifest";

/**
 * Settings configures, modules operate.
 *
 * These pages used to be second copies of record screens — the supplier list, purchase orders,
 * the inbox, reports, the run log — which gave two editors for one table and a copy that always
 * fell behind. The Center keeps the address and hands over to the module that owns the rows.
 */
describe("module links in the Center", () => {
  const render = (to) =>
    renderToStaticMarkup(
      <I18nProvider>
        <MemoryRouter>
          <ModuleLinkPage to={to} title="Suppliers" isAr={false} />
        </MemoryRouter>
      </I18nProvider>
    );

  test("the card names the reason and links to the real screen", () => {
    const html = render("/cashier/suppliers");
    expect(html).toContain("records, not settings");
    expect(html).toContain('href="/cashier/suppliers"');
  });

  test("every declared link points outside the Center", () => {
    const links = allPageLinks();
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link.to.startsWith("/")).toBe(true);
      expect(link.to.startsWith("/settings")).toBe(false);
    }
  });

  test("a linked page belongs to a section that owns it", () => {
    const purchasing = sectionBySlug("purchasing");
    expect(pageLink(purchasing, "suppliers")).toBe("/cashier/suppliers");
    expect(pageLink(purchasing, "purchase-orders")).toBe("/cashier/purchases");
    // ...and a page the Center really configures has no link.
    expect(pageLink(purchasing, "purchasing-settings")).toBeNull();
    expect(pageLink(purchasing, "approval-limits")).toBeNull();
  });

  test("a linked page stays a tab, so old bookmarks still land somewhere true", () => {
    // The tab strip is built from sectionPages(); removing the page would 404 the bookmark
    // instead of explaining the move.
    const customers = sectionBySlug("customers");
    const slugs = customers.pages.map((p) => (typeof p === "string" ? p : p.slug));
    expect(slugs).toContain("inbox");
    expect(pageLink(customers, "inbox")).toBe("/inbox");
  });
});
