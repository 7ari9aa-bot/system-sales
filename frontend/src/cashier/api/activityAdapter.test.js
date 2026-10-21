import { describe, expect, it } from "vitest";
import {
  ACTIVITY_PAGE,
  activityFromApi,
  activityPageFromApi,
  activityQuery,
  employeesIn,
  movementDetail,
  shiftDetail,
  supplierReturnDetail,
} from "./activityAdapter";

const ev = (o = {}) => ({ occurred_at: "2026-10-21T00:02:10Z", kind: "sale", ref_id: "r1", doc: "POS-1", amount: "40.00", actor_id: "u1", actor_name: "منى", detail: "x", ...o });

describe("machine values become Arabic", () => {
  it("movement reason and direction", () => {
    expect(movementDetail("supplier_return / out")).toBe("مرتجع لمورد • خروج");
    expect(movementDetail("sale / out")).toBe("بيع • خروج");
    expect(movementDetail("supplier_return_reversal / in")).toBe("رجوع مرتجع مورد للرف • دخول");
  });
  it("an unknown reason stays visible instead of going blank", () => {
    expect(movementDetail("weird / in")).toBe("weird • دخول");
    expect(movementDetail("")).toBe("");
    expect(movementDetail(null)).toBe("");
  });
  it("shift open / close, naming a shortage or an overage only when there is one", () => {
    expect(shiftDetail("opened")).toBe("تم فتح الوردية");
    expect(shiftDetail("closed variance=0")).toBe("تم إغلاق الوردية بدون عجز أو زيادة");
    expect(shiftDetail("closed variance=0.00")).toBe("تم إغلاق الوردية بدون عجز أو زيادة");
    expect(shiftDetail("closed variance=-3.50")).toBe("تم إغلاق الوردية • عجز 3.50");
    expect(shiftDetail("closed variance=12.00")).toBe("تم إغلاق الوردية • زيادة 12.00");
    expect(shiftDetail("something else")).toBe("something else");
  });
  it("a supplier return keeps the supplier and translates only the status", () => {
    expect(supplierReturnDetail("مورد الشاشة · accepted")).toBe("مورد الشاشة • مقبول");
    expect(supplierReturnDetail("مورد · rejected")).toBe("مورد • مرفوض");
    expect(supplierReturnDetail("مورد · pending")).toBe("مورد • قيد المراجعة");
    expect(supplierReturnDetail("بدون حالة")).toBe("بدون حالة");
  });
});

describe("activityFromApi", () => {
  it("keeps money as the backend's exact text and never turns it into a float", () => {
    const r = activityFromApi(ev({ amount: "120.50" }));
    expect(r.amount).toBe("120.50");
    expect(r.quantity).toBeNull();
  });
  it("an inventory row carries a unit count, not money", () => {
    const r = activityFromApi(ev({ kind: "inventory", amount: "3", detail: "sale / out" }));
    expect(r.amount).toBeNull();
    expect(r.quantity).toBe(3);
    expect(r.details).toBe("بيع • خروج");
  });
  it("the id is unique across kinds even if two tables share a uuid", () => {
    expect(activityFromApi(ev({ kind: "sale", ref_id: "a", event_key: "sale:a:x" })).id).not.toBe(activityFromApi(ev({ kind: "return", ref_id: "a", event_key: "return:a:x" })).id);
  });
  it("a shift's open and close share a ref_id but are two distinct rows", () => {
    const open = activityFromApi(ev({ kind: "shift", ref_id: "s1", doc: "فتح وردية", event_key: "shift:s1:فتح وردية" }));
    const close = activityFromApi(ev({ kind: "shift", ref_id: "s1", doc: "إغلاق وردية", event_key: "shift:s1:إغلاق وردية" }));
    expect(open.id).not.toBe(close.id);
  });
  it("falls back to kind+ref+doc if an older server sends no event_key", () => {
    const a = activityFromApi(ev({ kind: "shift", ref_id: "s1", doc: "فتح وردية" }));
    const b = activityFromApi(ev({ kind: "shift", ref_id: "s1", doc: "إغلاق وردية" }));
    expect(a.id).not.toBe(b.id);
  });
  it("a row with no actor (a stock movement) has an empty employee, not 'undefined'", () => {
    const r = activityFromApi(ev({ actor_id: null, actor_name: null }));
    expect(r.employee).toBe("");
    expect(r.employeeId).toBeNull();
  });
  it("a missing detail is an empty string", () => {
    expect(activityFromApi(ev({ detail: null })).details).toBe("");
  });
});

describe("activityPageFromApi", () => {
  it("returns the rows and the next cursor", () => {
    const p = activityPageFromApi({ items: [ev(), ev({ ref_id: "r2" })], next_cursor: "abc" });
    expect(p.rows).toHaveLength(2);
    expect(p.next).toBe("abc");
  });
  it("survives an empty or malformed payload", () => {
    expect(activityPageFromApi(null)).toEqual({ rows: [], next: null });
    expect(activityPageFromApi({})).toEqual({ rows: [], next: null });
    expect(activityPageFromApi({ items: "no" })).toEqual({ rows: [], next: null });
  });
});

describe("activityQuery", () => {
  it("always sends the page size and leaves empty filters out", () => {
    expect(activityQuery()).toBe(`limit=${ACTIVITY_PAGE}`);
  });
  it("encodes every filter, trimming the search", () => {
    const q = new URLSearchParams(activityQuery({ term: "  فاتورة ", type: "sale", employeeId: "u1", from: "2026-10-01", to: "2026-10-21", cursor: "c" }));
    expect(q.get("q")).toBe("فاتورة");
    expect(q.get("kinds")).toBe("sale");
    expect(q.get("actor_id")).toBe("u1");
    expect(q.get("date_from")).toBe("2026-10-01");
    expect(q.get("date_to")).toBe("2026-10-21");
    expect(q.get("cursor")).toBe("c");
  });
  it("a whitespace-only search is not sent", () => {
    expect(new URLSearchParams(activityQuery({ term: "   " })).has("q")).toBe(false);
  });
  it("a search with & or % cannot break out into another parameter", () => {
    const q = new URLSearchParams(activityQuery({ term: "a&actor_id=evil%" }));
    expect(q.get("q")).toBe("a&actor_id=evil%");
    expect(q.has("actor_id")).toBe(false);
  });
});

describe("employeesIn", () => {
  it("lists each employee once, sorted, skipping rows with no actor", () => {
    const rows = [
      activityFromApi(ev({ actor_id: "u2", actor_name: "ياسر" })),
      activityFromApi(ev({ actor_id: "u1", actor_name: "منى" })),
      activityFromApi(ev({ actor_id: "u1", actor_name: "منى" })),
      activityFromApi(ev({ actor_id: null, actor_name: null })),
    ];
    expect(employeesIn(rows)).toEqual([{ id: "u2", name: "ياسر" }, { id: "u1", name: "منى" }].sort((a, b) => a.name.localeCompare(b.name, "ar")));
  });
});
