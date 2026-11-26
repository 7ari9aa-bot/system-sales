import { describe, expect, test } from "vitest";
import ar from "@/lib/i18n/ar";
import en from "@/lib/i18n/en";
import { invoiceRow } from "./BillingPanels";

const SECTION_19_PAGES = ["current-plan", "usage", "invoices", "billing-details"];

describe("section 19 copy", () => {
  test("every live page has a title and a description in both languages", () => {
    for (const page of SECTION_19_PAGES) {
      for (const [lang, dict] of [
        ["ar", ar],
        ["en", en],
      ]) {
        for (const field of ["title", "desc"]) {
          const key = `settings.billing.pages.${page}.${field}`;
          expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
        }
      }
    }
  });

  test("the panels' labels exist in both languages", () => {
    const keys = [
      "settings.billing.plan.title",
      "settings.billing.plan.desc",
      "settings.billing.plan.none",
      "settings.billing.plan.name",
      "settings.billing.plan.price",
      "settings.billing.plan.status",
      "settings.billing.plan.trialEnds",
      "settings.billing.plan.renews",
      "settings.billing.plan.cancelAtEnd",
      "settings.billing.plan.whereToEdit",
      "settings.billing.usage.title",
      "settings.billing.usage.desc",
      "settings.billing.usage.empty",
      "settings.billing.usage.whereToEdit",
      "settings.billing.usage.aiConsumption",
      "settings.billing.invoices.title",
      "settings.billing.invoices.desc",
      "settings.billing.invoices.empty",
      "settings.billing.invoices.whereToEdit",
      "settings.billing.billingDetails.title",
      "settings.billing.billingDetails.desc",
      "settings.billing.billingDetails.body",
    ];
    for (const key of keys) {
      expect(ar[key], `ar is missing ${key}`).toBeTruthy();
      expect(en[key], `en is missing ${key}`).toBeTruthy();
    }
  });

  test("every subscription status the API can return has a label", () => {
    // `GET /billing/subscription` returns one of these, and a page that renders the raw
    // enum in an otherwise Arabic screen is the failure this catches.
    for (const status of ["active", "trialing", "past_due", "canceled", "expired"]) {
      for (const [lang, dict] of [
        ["ar", ar],
        ["en", en],
      ]) {
        const key = `settings.billing.plan.statuses.${status}`;
        expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
      }
    }
  });
});

describe("invoiceRow", () => {
  test("prints the money with its currency and skips what the row does not have", () => {
    const pairs = invoiceRow({
      id: "i1",
      number: "INV-1",
      status: "paid",
      total: "1200.00",
      currency: "EGP",
      issued_at: "2026-11-01T10:00:00Z",
      period_start: null,
      period_end: null,
    });
    const asObject = Object.fromEntries(pairs);
    expect(asObject.number).toBe("INV-1");
    expect(asObject.status).toBe("paid");
    expect(asObject.total).toBe("1200.00 EGP");
    expect(asObject.period).toBeUndefined();
  });

  test("a snapshot invoice shows its period", () => {
    const pairs = Object.fromEntries(
      invoiceRow({ number: "INV-2", period_start: "2026-10-01", period_end: "2026-10-31" }),
    );
    expect(pairs.period).toBe("2026-10-01 → 2026-10-31");
  });

  test("an unusable row is empty, never a throw", () => {
    expect(invoiceRow(null)).toEqual([]);
    expect(invoiceRow("nope")).toEqual([]);
  });
});
