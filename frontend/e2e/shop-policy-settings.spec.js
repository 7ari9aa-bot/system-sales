import { expect, test } from "@playwright/test";

// UI contract: only HTTP transport is mocked. The tab is drawn from the settings engine's own
// definitions, so what it shows and what it sends are checked against that contract.
const def = (o) => ({ domain: "pos", enforced: true, scopes: ["tenant", "branch"], default: 30, min_value: 0, max_value: 365, label_ar: "", description_ar: "", ...o });
const DEFS = [
  def({ key: "pos.return_max_days", type: "number", label_ar: "مهلة المرتجع (أيام)", description_ar: "أقصى عدد أيام بعد البيع." }),
  def({ key: "pos.exchange_max_days", type: "number", default: 0, label_ar: "مهلة الاستبدال (أيام)" }),
  def({ key: "pos.return_restock_default", type: "bool", default: true, label_ar: "إرجاع القطعة للرف افتراضيًا" }),
  def({ key: "pos.return_reasons", type: "list", scopes: ["tenant"], default: ["size", "defect"], label_ar: "أسباب المرتجع" }),
  def({ key: "pos.not_wired_yet", type: "bool", enforced: false, label_ar: "إعداد غير مربوط" }),
];
const eff = (key, value) => ({ key, value, scope: "tenant", is_default: false, is_inherited: false });
const EFFECTIVE = {
  "pos.return_max_days": eff("pos.return_max_days", 30),
  "pos.exchange_max_days": eff("pos.exchange_max_days", 0),
  "pos.return_restock_default": eff("pos.return_restock_default", true),
  "pos.return_reasons": eff("pos.return_reasons", ["size", "defect"]),
};
const json = (route, data, status = 200) => route.fulfill({ status, json: data });

async function setup(page, { onBulk } = {}) {
  await page.context().addCookies([{ name: "csrf_token", value: "ui-test", url: new URL(process.env.BASE_URL || "http://127.0.0.1:4173").origin }]);
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "u", email: "t@e.com", full_name: "T", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/settings/definitions") return json(route, DEFS);
    if (path === "/api/v1/settings/effective") return json(route, EFFECTIVE);
    if (path === "/api/v1/settings/bulk") return onBulk ? onBulk(route) : json(route, []);
    return json(route, []);
  });
  await page.goto("/settings/pos");
  await page.getByRole("tab", { name: "سياسة المحل" }).click();
}
const field = (page, label) => page.getByLabel(label, { exact: true });

test("shows only settings the server really enforces, with the engine's own wording", async ({ page }) => {
  await setup(page);
  await expect(field(page, "مهلة المرتجع (أيام)")).toHaveValue("30");
  await expect(field(page, "أسباب المرتجع")).toHaveValue("size\ndefect");
  await expect(page.getByText("أقصى عدد أيام بعد البيع.")).toBeVisible();
  await expect(page.getByText("إعداد غير مربوط")).toHaveCount(0);
});

test("save is off until something changes, then sends only what changed", async ({ page }) => {
  let sent = null;
  await setup(page, { onBulk: (route) => { sent = route.request().postDataJSON(); return json(route, []); } });
  const save = page.getByRole("button", { name: "حفظ", exact: true });
  await expect(save).toBeDisabled();
  await field(page, "مهلة المرتجع (أيام)").fill("14");
  await field(page, "أسباب المرتجع").fill("size\n\ntoo_small\nsize");
  await expect(save).toBeEnabled();
  await save.click();
  await expect.poll(() => sent).not.toBeNull();
  expect(sent).toEqual({ scope: "tenant", settings: { "pos.return_max_days": 14, "pos.return_reasons": ["size", "too_small"] } });
});

test("a number outside the server's bounds is refused on the spot and cannot be saved", async ({ page }) => {
  let called = false;
  await setup(page, { onBulk: (route) => { called = true; return json(route, []); } });
  await field(page, "مهلة المرتجع (أيام)").fill("400");
  await expect(page.getByRole("alert")).toContainText("365");
  await expect(page.getByRole("button", { name: "حفظ", exact: true })).toBeDisabled();
  expect(called).toBe(false);
});

test("a refusal from the server is shown, not reported as saved", async ({ page }) => {
  await setup(page, { onBulk: (route) => json(route, { detail: "missing permission: settings:write" }, 403) });
  await field(page, "مهلة المرتجع (أيام)").fill("10");
  await page.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(page.getByText("تم حفظ")).toHaveCount(0);
  await expect(page.getByText(/صلاحية/)).toBeVisible();
});
