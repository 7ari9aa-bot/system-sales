import { describe, expect, it } from "vitest";
import {
  ATTENTION_ORDER,
  GROUPS,
  attentionLabel,
  groupQuery,
  hoursLeftText,
  receiptFromApi,
  statusLabel,
  summaryCards,
  trackingErrorMessage,
} from "./receiptTracking";

const api = (o = {}) => ({
  id: "r1", invoice_number: "R-1", document_type: "simplified", status: "reported", attention: "ok",
  hours_left: null, errors: [], attempts: 0, next_attempt_at: null, issued_at: "2026-11-21T08:00:00Z",
  order_id: "o1", authority_uuid: "abc", ...o,
});

describe("hours left, said the way a shop owner would", () => {
  it.each([
    [0, "انتهت المهلة"],
    [0.4, "أقل من ساعة"],
    [1, "ساعة واحدة"],
    [2, "ساعتان"],
    [5, "5 ساعات"],
    [11, "11 ساعة"],
    [16, "16 ساعة"],
    [24, "يوم واحد"],
    [30, "يوم و6 ساعات"],
    [48, "يومان"],
    [86, "3 أيام و14 ساعة"],
    [96, "4 أيام"],
  ])("%s h -> %s", (h, text) => expect(hoursLeftText(h)).toBe(text));

  it("says nothing for a receipt that has no deadline", () => {
    expect(hoursLeftText(null)).toBe("");
    expect(hoursLeftText(undefined)).toBe("");
  });
});

describe("a receipt row", () => {
  it("keeps the backend's own words and adds Arabic labels", () => {
    const r = receiptFromApi(api({ status: "rejected", attention: "urgent", hours_left: 16, errors: ["x: 1 y"] }));
    expect(r).toMatchObject({ id: "r1", number: "R-1", status: "rejected", attention: "urgent", hoursLeft: 16 });
    expect(r.statusText).toBe("رفضتها المصلحة");
    expect(r.deadlineText).toBe("16 ساعة");
    expect(r.errors).toEqual(["x: 1 y"]);
  });

  it("a receipt that needs nothing has no deadline text", () => {
    expect(receiptFromApi(api()).deadlineText).toBe("");
  });

  it("never throws on a missing list of errors", () => {
    expect(receiptFromApi(api({ errors: null })).errors).toEqual([]);
  });

  it("an unknown status shows its raw value instead of hiding it", () => {
    expect(statusLabel("something_new")).toBe("something_new");
  });

  it("an expired receipt tells the owner what is left to do", () => {
    expect(attentionLabel("expired")).toMatch(/طلب تقديم متأخر/);
  });
});

describe("the order the owner reads", () => {
  it("expired, then urgent, then fix, then retrying, then ok", () => {
    expect(ATTENTION_ORDER).toEqual(["expired", "urgent", "fix", "retrying", "ok"]);
  });
});

describe("the counters at the top", () => {
  const s = { total: 10, accepted: 5, waiting: 1, retrying: 1, rejected: 3, fix_now: 2, urgent: 1, expired: 1, needs_attention: 3, warn_hours: 24 };

  it("shows what needs the owner first", () => {
    const cards = summaryCards(s);
    expect(cards[0]).toMatchObject({ key: "needs_attention", value: 3, tone: "danger" });
    expect(cards.map((c) => c.key)).toEqual(["needs_attention", "urgent", "accepted", "waiting", "retrying"]);
  });

  it("a shop with nothing to fix gets a calm first card", () => {
    const cards = summaryCards({ ...s, needs_attention: 0, urgent: 0, expired: 0, rejected: 0, fix_now: 0 });
    expect(cards[0].tone).toBe("ok");
  });

  it("an urgent receipt makes its card loud; none makes it quiet", () => {
    expect(summaryCards(s).find((c) => c.key === "urgent").tone).toBe("danger");
    expect(summaryCards({ ...s, urgent: 0 }).find((c) => c.key === "urgent").tone).toBe("muted");
  });

  it("missing numbers read as zero, never NaN or blank", () => {
    const cards = summaryCards({});
    expect(cards.every((c) => c.value === 0)).toBe(true);
  });
});

describe("the filter", () => {
  it("offers exactly the groups the backend accepts", () => {
    expect(GROUPS.map((g) => g.value)).toEqual(["", "rejected", "retrying", "waiting", "accepted", "cancelled"]);
  });

  it("builds a query with only what was chosen", () => {
    expect(groupQuery({ group: "" })).toBe("");
    expect(groupQuery({ group: "rejected" })).toBe("?group=rejected");
    expect(groupQuery({ group: "accepted", from: "2026-11-01", to: "2026-11-21", limit: 50, offset: 100 })).toBe(
      "?group=accepted&date_from=2026-11-01&date_to=2026-11-21&limit=50&offset=100",
    );
  });

  it("drops a group the backend would refuse instead of sending it", () => {
    expect(groupQuery({ group: "nonsense" })).toBe("");
  });
});

describe("a refusal in plain Arabic", () => {
  it("a missing permission says so", () => {
    expect(trackingErrorMessage({ status: 403 })).toMatch(/صلاحية/);
  });
  it("anything else is a calm retry message, never a raw error", () => {
    expect(trackingErrorMessage({ status: 500, message: "Traceback ..." })).not.toMatch(/Traceback/);
  });
});
