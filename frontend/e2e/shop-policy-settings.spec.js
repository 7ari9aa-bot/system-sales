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
  await page.addInitScript((l) => localStorage.setItem("salesos.lang", l), "ar");
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/me") return json(route, { id: "u", email: "t@e.com", full_name: "T", is_active: true, tenants: [{ id: "tenant", name: "Shop", role_code: "owner" }] });
    if (path === "/api/v1/settings/definitions") return json(route, DEFS);
    if (path === "/api/v1/settings/effective") return json(route, EFFECTIVE);
    if (path === "/api/v1/settings/bulk") return onBulk ? onBulk(route) : json(route, []);
    return json(route, []);
  });
  await page.goto("/settings/store/business-policies");
}
const field = (page, label) => page.getByLabel(label, { exact: true });

test("shows only settings the server really enforces, with the engine's own wording", async ({ page }) => {
  await setup(page);
  await expect(field(page, "مهلة المرتجع (أيام)")).toHaveValue("30");
  await expect(field(page, "أسباب المرتجع")).toHaveValue("size, defect");
  await expect(page.getByText("أقصى عدد أيام بعد البيع.")).toBeVisible();
  // a key nothing enforces is still named, and says so, but offers no control that looks live
  await expect(page.getByText("إعداد غير مربوط")).toBeVisible();
  await expect(page.getByRole("switch", { name: "إعداد غير مربوط" })).toBeDisabled();
});

test("nothing to save offers no save, and a save sends only what changed", async ({ page }) => {
  let sent = null;
  await setup(page, { onBulk: (route) => { sent = route.request().postDataJSON(); return json(route, []); } });
  const save = page.getByRole("button", { name: "حفظ", exact: true });
  // an untouched screen has nothing to send, so it does not offer a button that would send nothing
  await expect(save).toHaveCount(0);
  await field(page, "مهلة المرتجع (أيام)").fill("14");
  await field(page, "أسباب المرتجع").fill("size,, too_small, size");
  await expect(save).toBeVisible();
  await save.click();
  await expect.poll(() => sent).not.toBeNull();
  expect(sent.settings).toEqual({ "pos.return_max_days": 14, "pos.return_reasons": ["size", "too_small"] });
  expect(sent.scope).toBe("tenant");
});

test("the field states the server's own bounds instead of inventing its own", async ({ page }) => {
  await setup(page);
  const box = field(page, "مهلة المرتجع (أيام)");
  // min/max come from the definitions payload, so the browser refuses 400 before any request
  await expect(box).toHaveAttribute("min", "0");
  await expect(box).toHaveAttribute("max", "365");
  expect(await box.evaluate((el) => el.checkValidity())).toBe(true);
  await box.fill("400");
  expect(await box.evaluate((el) => el.checkValidity())).toBe(false);
});

test("a refusal from the server is shown, not reported as saved", async ({ page }) => {
  await setup(page, { onBulk: (route) => json(route, { detail: "missing permission: settings:write" }, 403) });
  await field(page, "مهلة المرتجع (أيام)").fill("10");
  await page.getByRole("button", { name: "حفظ", exact: true }).click();
  await expect(page.getByText("تم حفظ")).toHaveCount(0);
  // the server's own words, not a friendly rewrite that hides which permission is missing
  await expect(page.getByText("missing permission: settings:write")).toBeVisible();
});

test("a switch is visibly on or off: this page is outside the cashier theme, so a missing colour would make both look the same", async ({ page }) => {
  await setup(page);
  const sw = page.getByRole("switch", { name: "إرجاع القطعة للرف افتراضيًا" });
  const fill = () => sw.evaluate((el) => getComputedStyle(el).backgroundColor);
  await expect(sw).toHaveAttribute("data-state", "checked");
  const on = await fill();
  expect(on, "an on switch must have a fill").not.toBe("rgba(0, 0, 0, 0)");
  await sw.click();
  await expect(sw).toHaveAttribute("data-state", "unchecked");
  // the switch animates its colour, so read it once the transition has settled
  await page.waitForTimeout(300);
  const off = await fill();
  expect(off, "an off switch must have a fill").not.toBe("rgba(0, 0, 0, 0)");
  expect(off, "on and off must not look the same").not.toBe(on);
});
