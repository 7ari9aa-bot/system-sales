import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TrackingView } from "./ReceiptTracking";
import { receiptFromApi } from "@/applications/apparel/api/receiptTracking";

const r = (o) => receiptFromApi({ id: "x" + Math.random(), invoice_number: "R-1", document_type: "simplified", status: "reported", attention: "ok", hours_left: null, errors: [], attempts: 0, issued_at: "2026-11-21T08:00:00Z", ...o });
const SUMMARY = { total: 4, accepted: 2, waiting: 0, retrying: 0, rejected: 2, fix_now: 2, urgent: 1, expired: 0, needs_attention: 2 };
const draw = (receipts, over = {}) => renderToStaticMarkup(<TrackingView summary={SUMMARY} receipts={receipts} total={receipts.length} group="" {...over} />);

describe("the tracking screen", () => {
  it("shows the counters, what needs the owner first", () => {
    const html = draw([]);
    expect(html.indexOf('data-card="needs_attention"')).toBeLessThan(html.indexOf('data-card="accepted"'));
    expect(html).toContain("تحتاج إجراءً منك");
  });

  it("a refused receipt shows why and how long is left", () => {
    const html = draw([r({ status: "rejected", attention: "urgent", hours_left: 16, errors: ["ItemCode invalid"] })]);
    expect(html).toContain('data-attention="urgent"');
    expect(html).toContain("رفضتها المصلحة");
    expect(html).toContain("16 ساعة");
    expect(html).toContain("ItemCode invalid");
  });

  it("an expired one says a late-submission request is needed, with no countdown", () => {
    const html = draw([r({ status: "rejected", attention: "expired", hours_left: 0 })]);
    expect(html).toMatch(/طلب تقديم متأخر/);
    expect(html).not.toContain("الوقت المتبقي للتصحيح");
  });

  it("an accepted receipt is quiet: no deadline, no warning", () => {
    const html = draw([r({})]);
    expect(html).toContain("قبلتها المصلحة");
    expect(html).not.toContain("الوقت المتبقي");
  });

  it("a retrying receipt says the system is handling it, with no countdown", () => {
    const html = draw([r({ status: "failed", attention: "retrying" })]);
    expect(html).toContain("النظام بيعيد الإرسال لوحده");
    expect(html).not.toContain("الوقت المتبقي");
  });

  it("an empty shop gets a friendly message, not a blank page", () => {
    expect(draw([])).toContain("مفيش إيصالات هنا");
  });

  it("the chosen filter is marked selected", () => {
    const html = draw([], { group: "rejected" });
    expect(html).toMatch(/aria-selected="true"[^>]*>مرفوضة/);
  });

  it("says when the list is cut short", () => {
    expect(renderToStaticMarkup(<TrackingView summary={SUMMARY} receipts={[r({})]} total={250} group="" />)).toContain("بنعرض 1 من 250");
  });
});
