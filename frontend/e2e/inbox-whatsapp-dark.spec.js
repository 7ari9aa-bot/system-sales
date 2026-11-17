import { expect, test } from "@playwright/test";

// The WhatsApp inbox in dark mode: the colours really change, text stays
// readable (measured contrast, not just a class), and light mode is untouched.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const now = () => new Date().toISOString();

async function boot(page, theme) {
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cu1", customer_name: "Sara", customer_phone: "201001234560", unread_count: 2, last_message_at: now(), last_customer_message_at: now(), last_message_preview: "مرحبا، عايز أسأل عن الطلب", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.addInitScript((t) => localStorage.setItem("salesos.theme", t), theme);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (u.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@e.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (u.pathname === "/api/v1/inbox") return send({ items: [row], next_cursor: null });
    if (u.pathname.endsWith("/messages")) return send({ items: [
      { id: "m1", direction: "inbound", body: "مرحبا، عايز أسأل عن الطلب", content_type: "text", status: "received", created_at: now(), reactions: [] },
      { id: "m2", direction: "outbound", body: "أهلا، تمام يا فندم", content_type: "text", status: "read", created_at: now(), sender_type: "agent", reactions: [] },
    ], next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-list")).toBeVisible();
  await page.getByText("Sara").first().click();
  await expect(page.getByTestId("chat-header")).toBeVisible();
  await expect(page.getByText("أهلا، تمام يا فندم")).toBeVisible();
}

// WCAG contrast of an element's text against the colour actually painted behind it.
const contrastOf = (page, locator) => locator.evaluate((el) => {
  const parse = (c) => { const m = c.match(/[\d.]+/g).map(Number); return { r: m[0], g: m[1], b: m[2], a: m[3] ?? 1 }; };
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  let bg = { r: 255, g: 255, b: 255, a: 0 };
  for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c.a > 0.95) { bg = c; break; } }
  const fg = parse(getComputedStyle(el).color);
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return { ratio: (a + 0.05) / (b + 0.05), fg: getComputedStyle(el).color, bg: `rgb(${bg.r}, ${bg.g}, ${bg.b})` };
});

const paint = (page, testid) => page.getByTestId(testid).evaluate((el) => getComputedStyle(el).backgroundColor);

test("dark mode repaints the list, the chat and the input bar", async ({ page }) => {
  await boot(page, "dark");
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(true);
  // WhatsApp Web's dark surfaces
  expect(await paint(page, "chat-list")).toBe("rgb(17, 27, 33)");
  expect(await paint(page, "chat-header")).toBe("rgb(32, 44, 51)"); // a shade lighter than the list, as on WhatsApp Web
});

test("light mode keeps WhatsApp's own light colours", async ({ page }) => {
  await boot(page, "light");
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(false);
  expect(await paint(page, "chat-list")).toBe("rgb(255, 255, 255)");
});

for (const theme of ["light", "dark"]) {
  test(`${theme}: the text people read stays readable (WCAG AA, 4.5:1)`, async ({ page }) => {
    await boot(page, theme);
    const spots = {
      "customer name": page.getByTestId("chat-row").getByText("Sara").first(),
      "list preview": page.getByTestId("chat-row").getByText("مرحبا، عايز أسأل عن الطلب"),
      "incoming message": page.getByText("مرحبا، عايز أسأل عن الطلب").last(),
      "outgoing message": page.getByText("أهلا، تمام يا فندم"),
      "header name": page.getByTestId("chat-header").getByText("Sara").first(),
    };
    for (const [name, loc] of Object.entries(spots)) {
      const { ratio, fg, bg } = await contrastOf(page, loc);
      expect(ratio, `${theme} ${name}: ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });
}

test("dark: the bubbles are told apart", async ({ page }) => {
  await boot(page, "dark");
  const painted = (text) => page.getByText(text).last().evaluate((el) => { for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (!c.endsWith(", 0)") && c !== "rgba(0, 0, 0, 0)") return c; } });
  expect(await painted("أهلا، تمام يا فندم")).not.toBe(await painted("مرحبا، عايز أسأل عن الطلب"));
});

// A pixel check of the real screen, not of a list of elements we thought of: any
// light slab left in dark mode (an unconverted colour, a light wallpaper) shows up.
test("dark: no large light area is left anywhere on the screen", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 760 });
  await boot(page, "dark");
  await page.waitForTimeout(400);
  const png = await page.screenshot();
  const share = await page.evaluate(async (b64) => {
    const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode();
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data; let light = 0, n = 0;
    for (let i = 0; i < d.length; i += 16) { n++; if ((d[i] + d[i + 1] + d[i + 2]) / 3 > 200) light++; }
    return light / n;
  }, png.toString("base64"));
  // Text and icons are light on purpose; a whole panel is not. 8% is far above text, far below a slab.
  expect(share, `${Math.round(share * 100)}% of the screen is light`).toBeLessThan(0.08);
});

test("dark: the attach menu and the preview follow the theme too", async ({ page }) => {
  await boot(page, "dark");
  await page.getByTestId("composer-attach").click();
  expect(await paint(page, "attach-menu")).toBe("rgb(17, 27, 33)");
  await page.getByTestId("attach-input-media").setInputFiles({ name: "a.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64") });
  await expect(page.getByTestId("attach-preview")).toBeVisible();
  const { ratio } = await contrastOf(page, page.getByTestId("attach-caption"));
  expect(ratio).toBeGreaterThanOrEqual(4.5);
});
