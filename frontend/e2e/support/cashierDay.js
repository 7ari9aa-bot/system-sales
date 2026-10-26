const LINES = Array.from({ length: 30 }, (_, i) => ({ variant_id: `v-${i}`, title: `صنف ${i + 1}`, sku: `SKU-${i}`, quantity: 2, unit_price: "50.00", total: "100.00", returned_qty: 0 }));
const RECEIPT = { receipt: { id: "inv-1", number: "INV-1", issued_at: "2026-10-26T10:00:00Z", change_amount: "0", tendered_amount: "3000.00", kind: "sale", session_id: "s1", order_id: "o-1" },
  order: { id: "o-1", number: "ORD-1", discount_total: "0", grand_total: "3000.00", status: "paid", fully_returned: false }, lines: LINES, tenders: [{ method: "cash", amount: "3000.00" }] };
// A started cashier day with one 30-line sale, so the real sell / return / exchange screens render (not the "till not set up" card).
export async function mockCashierDay(page) {
  await page.context().addCookies([{ name: "csrf_token", value: "test", url: "http://127.0.0.1:4173" }]);
  await page.route("**/api/v1/**", (r) => {
    const u = r.request().url();
    if (u.includes("/auth/me")) return r.fulfill({ json: { id: "u1", email: "t@e.com", full_name: "T", role: "owner" } });
    if (/\/pos\/registers$/.test(u.split("?")[0])) return r.fulfill({ json: [{ id: "r1", name: "Main", code: "MAIN", is_active: true }] });
    if (u.includes("/working-session")) return r.fulfill({ json: { started: true, session: { id: "s1", register_id: "r1", status: "OPEN", opening_float: "100.00", opened_at: "2026-10-26T08:00:00Z" } } });
    if (/\/pos\/receipts\/search/.test(u)) return r.fulfill({ json: [{ ...RECEIPT.receipt, order_number: "ORD-1", total: "3000.00" }] });
    if (/\/pos\/receipts\/[^/?]+/.test(u)) return r.fulfill({ json: RECEIPT });
    if (/\/pos\/sessions\/[^/]+\/receipts/.test(u)) return r.fulfill({ json: [{ ...RECEIPT.receipt, order_number: "ORD-1", total: "3000.00" }] });
    return r.fulfill({ json: [] });
  });
}
