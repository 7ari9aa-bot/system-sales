import { expect, test } from "@playwright/test";

// Measured fidelity to WhatsApp Web. These are the things a screenshot hides: a panel
// quietly inheriting the app's font or brown ink, a 1px gap above the header, or the
// list stopping short of the bottom. Each was found by measuring the real page.
const ORIGIN = process.env.BASE_URL || "http://127.0.0.1:4173";
const now = () => new Date().toISOString();

async function boot(page, theme, size) {
  await page.setViewportSize(size);
  const row = { id: "c1", channel: "whatsapp", status: "open", customer_id: "cu1", customer_name: "Sara", customer_phone: "201001234560", unread_count: 0, last_message_at: now(), last_customer_message_at: now(), last_message_preview: "x", last_message_content_type: "text", pinned_at: null, muted_until: null, archived_at: null, marked_unread: false };
  await page.context().addCookies([{ name: "csrf_token", value: "x", url: new URL(ORIGIN).origin }]);
  await page.addInitScript((t) => localStorage.setItem("salesos.theme", t), theme);
  await page.route("**/api/v1/**", async (route) => {
    const u = new URL(route.request().url());
    const send = (d) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(d) });
    if (u.pathname === "/api/v1/auth/me") return send({ id: "u", email: "m@e.com", full_name: "M", is_platform_admin: false, tenants: [{ id: "t", name: "Shop", slug: "shop", role_code: "owner" }] });
    if (u.pathname === "/api/v1/channels/status") return send([{ provider: "whatsapp", connected: true, enabled_for_me: true, locked: false, lifecycle: "connected", webhook_status: "active", account_name: "Shop" }]);
    if (u.pathname === "/api/v1/inbox") return send({ items: [row], next_cursor: null });
    if (u.pathname.endsWith("/messages")) return send({ items: [{ id: "m1", direction: "inbound", body: "مرحبا", content_type: "text", status: "received", created_at: now(), reactions: [] }], next_cursor: null });
    return send({ items: [], next_cursor: null });
  });
  await page.goto("/inbox", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.getByTestId("chat-list")).toBeVisible();
  await page.getByText("Sara").first().click();
  await expect(page.getByTestId("chat-header")).toBeVisible();
  // let /channels/status land, so the "connect a channel" hint is judged in its settled state
  await page.waitForResponse((r) => r.url().includes("/channels/status")).catch(() => {});
  await page.waitForTimeout(300);
}

const style = (page, id) => page.getByTestId(id).evaluate((el) => { const c = getComputedStyle(el); const b = el.getBoundingClientRect(); return { font: c.fontFamily, color: c.color, y: Math.round(b.y), bottom: Math.round(b.bottom) }; });

for (const theme of ["light", "dark"]) {
  test(`${theme}: the list, header and input all use WhatsApp's own font and ink`, async ({ page }) => {
    await boot(page, theme, { width: 1280, height: 780 });
    const ink = theme === "light" ? "rgb(17, 27, 33)" : "rgb(233, 237, 239)";
    for (const id of ["chat-list", "chat-header", "composer-input"]) {
      const s = await style(page, id);
      expect(s.font, `${id} font`).toContain("Segoe UI");
      expect(s.color, `${id} ink`).toBe(ink);
    }
  });
}

test("the header sits on the very top edge, with no 1px gap above it", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 780 });
  expect((await style(page, "chat-header")).y).toBe(0);
  expect((await style(page, "chat-list")).y).toBe(0);
});

test("with the channel connected, the list runs to the bottom of the screen", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 780 });
  expect((await style(page, "chat-list")).bottom).toBe(780);
});



test("dark mode: nothing bright is painted anywhere in the inbox", async ({ page }) => {
  await boot(page, "dark", { width: 1280, height: 780 });
  const bright = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll("body *")) {
      const b = el.getBoundingClientRect();
      if (b.width < 6 || b.height < 6 || b.bottom < 0 || b.top > innerHeight) continue;
      const c = getComputedStyle(el).backgroundColor.match(/[\d.]+/g)?.map(Number);
      if (!c || (c[3] ?? 1) < 0.5) continue;
      if (c[0] > 150 && c[1] > 150 && c[2] > 150) out.push(`${el.tagName}[${el.dataset.testid || ""}] rgb(${c[0]},${c[1]},${c[2]})`);
    }
    return out;
  });
  expect(bright).toEqual([]);
});

test("the WhatsApp avatar is the default disc: light blue in light mode (sampled from the real app), grey in dark", async ({ page }) => {
  for (const theme of ["light", "dark"]) {
    await boot(page, theme, { width: 1280, height: 780 });
    const want = theme === "light" ? "rgb(202, 236, 250)" : "rgb(106, 113, 117)";
    const bg = await page.getByTestId("chat-header").locator("div,span").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    const list = await page.getByTestId("chat-row").first().locator("div").first().evaluate((el) => getComputedStyle(el.querySelector("[aria-hidden]") || el).backgroundColor);
    expect([bg, list]).toContain(want);
  }
});

test("the list uses WhatsApp Web's own type sizes and 72px rows", async ({ page }) => {
  await boot(page, "light", { width: 1440, height: 900 });
  const m = await page.evaluate(() => {
    const row = document.querySelector("[data-testid=chat-row]");
    const px = (e) => parseFloat(getComputedStyle(e).fontSize);
    return {
      rowHeight: Math.round(row.getBoundingClientRect().height),
      name: px(row.querySelector("span[dir=auto]")),
      preview: px(row.querySelector("p")),
      search: px(document.querySelector("[data-testid=chat-list] input")),
      tab: px(document.querySelector("[data-testid=tab-all]")),
    };
  });
  expect(m).toMatchObject({ name: 17, preview: 14, search: 15, tab: 14 });
  expect(m.rowHeight).toBeGreaterThanOrEqual(72);
  expect(m.rowHeight).toBeLessThanOrEqual(73);
});

test("the chat header has no video or call controls, only search and more", async ({ page }) => {
  await boot(page, "light", { width: 1440, height: 900 });
  const labels = await page.getByTestId("chat-header").locator("button").evaluateAll((b) => b.map((x) => x.dataset.testid));
  expect(labels.filter((l) => l !== "header-back")).toEqual(["header-identity", "header-search", "header-more"]);
});

// A pixel check, not a CSS one: the earlier background-colour scan skipped anything under
// 6px, so a 5px light divider between the panes sailed through in dark mode.
test("dark mode: no bright vertical strip anywhere in the screenshot", async ({ page }) => {
  await boot(page, "dark", { width: 1440, height: 900 });
  const shot = await page.screenshot();
  const bright = await page.evaluate(async (b64) => {
    const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode();
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0);
    const cols = [];
    for (let x = 0; x < c.width; x++) {
      let hits = 0, n = 0;
      for (let y = 0; y < c.height; y += 6) { const [r, gg, bb] = g.getImageData(x, y, 1, 1).data; n++; if (Math.min(r, gg, bb) > 150) hits++; }
      if (hits / n > 0.5) cols.push(x);
    }
    return cols;
  }, shot.toString("base64"));
  expect(bright).toEqual([]);
});

// Colours sampled from a real WhatsApp Web screenshot (light mode), not from memory.
test("light: surfaces match the real WhatsApp Web screenshot", async ({ page }) => {
  await boot(page, "light", { width: 1024, height: 576 });
  const c = await page.evaluate(() => {
    const bg = (el) => getComputedStyle(el).backgroundColor;
    return {
      header: bg(document.querySelector("[data-testid=chat-header]")),
      list: bg(document.querySelector("[data-testid=chat-list]")),
      search: bg(document.querySelector("[data-testid=chat-list] input")),
      wallpaper: bg(document.querySelector("[data-testid=chat-header]").nextElementSibling),
    };
  });
  expect(c).toEqual({
    header: "rgb(255, 255, 255)",
    list: "rgb(255, 255, 255)",
    search: "rgb(246, 245, 244)",
    wallpaper: "rgb(245, 241, 235)",
  });
});

// The filter pills sampled from the real WhatsApp screenshot: the active one is
// pale green with a green hairline, the idle ones are WHITE with a grey hairline
// (not filled grey), all fully round.
test("filter pills match WhatsApp: active green, idle white with a hairline", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 720 });
  const css = (id) => page.getByTestId(`tab-${id}`).evaluate((el) => {
    const s = getComputedStyle(el);
    return { bg: s.backgroundColor, border: s.borderTopColor, width: s.borderTopWidth, radius: s.borderTopLeftRadius, color: s.color, h: el.getBoundingClientRect().height };
  });
  const active = await css("all");
  expect(active.bg).toBe("rgb(217, 253, 211)");
  expect(active.border).toBe("rgb(175, 202, 170)");
  const idle = await css("unread");
  expect(idle.bg).toBe("rgb(255, 255, 255)");
  expect(idle.border).toBe("rgb(204, 204, 204)");
  expect(idle.color).toBe("rgb(102, 102, 102)");
  expect(idle.width).toBe("1px");
  expect(parseFloat(idle.radius)).toBeGreaterThan(10);
  // The sampled pills are ~28px tall at 1x.
  expect(active.h).toBeGreaterThanOrEqual(26);
  expect(active.h).toBeLessThanOrEqual(32);
});

// The WhatsApp input is ONE white capsule: attach, emoji, the field and the mic all
// live inside it, with no border of their own and a soft shadow under it.
test("the input bar is a single white capsule holding every control", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 720 });
  await page.getByTestId("chat-row").first().click();
  const capsule = page.getByTestId("composer-capsule");
  await expect(capsule).toBeVisible();
  const cs = await capsule.evaluate((el) => { const s = getComputedStyle(el); return { bg: s.backgroundColor, r: parseFloat(s.borderTopLeftRadius), shadow: s.boxShadow, h: el.getBoundingClientRect().height }; });
  expect(cs.bg).toBe("rgb(255, 255, 255)");
  expect(cs.r).toBeGreaterThanOrEqual(24);
  expect(cs.shadow).not.toBe("none");
  expect(cs.h).toBeGreaterThanOrEqual(52);
  const box = await capsule.boundingBox();
  for (const id of ["composer-attach", "composer-emoji", "composer-input", "composer-voice"]) {
    const b = await page.getByTestId(id).boundingBox();
    expect(b.x, id).toBeGreaterThanOrEqual(box.x);
    expect(b.x + b.width, id).toBeLessThanOrEqual(box.x + box.width + 1);
    expect(b.y, id).toBeGreaterThanOrEqual(box.y - 1);
    expect(b.y + b.height, id).toBeLessThanOrEqual(box.y + box.height + 1);
  }
  const field = await page.getByTestId("composer-input").evaluate((el) => { const s = getComputedStyle(el); return { w: s.borderTopWidth, bg: s.backgroundColor }; });
  expect(field.w).toBe("0px");
  expect(field.bg).toBe("rgba(0, 0, 0, 0)");
  // attach is first from the left, like WhatsApp.
  const att = await page.getByTestId("composer-attach").boundingBox();
  const emo = await page.getByTestId("composer-emoji").boundingBox();
  expect(att.x).toBeLessThan(emo.x);
});

// Clicking the name opens the contact panel: a flat side panel (no floating shadow)
// that shows the number and the real reply-window state, nothing invented.
test("the contact panel is a flat side panel with the real number and reply window", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 720 });
  await page.getByTestId("chat-row").first().click();
  await page.getByTestId("header-identity").click();
  const panel = page.getByTestId("contact-info");
  await expect(panel).toBeVisible();
  const st = await panel.evaluate((el) => { const s = getComputedStyle(el); return { shadow: s.boxShadow, w: el.getBoundingClientRect().width }; });
  expect(st.shadow).toBe("none");
  expect(st.w).toBeLessThanOrEqual(390);
  await expect(page.getByTestId("info-about-phone")).toContainText("+20");
  await expect(page.getByTestId("info-window")).toBeVisible();
  const box = await panel.boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(1280);
  expect(box.x).toBeGreaterThanOrEqual(0);
});

// The strip around the input capsule is transparent (the chat wallpaper shows through),
// and the filter pills never scroll sideways.
test("the input strip is transparent and the filter pills have no scrollbar", async ({ page }) => {
  await boot(page, "light", { width: 1280, height: 720 });
  await page.getByTestId("chat-row").first().click();
  const strip = await page.getByTestId("composer-capsule").evaluate((el) => {
    let n = el.parentElement; const out = [];
    while (n && !n.matches('[data-testid="chat-view"], main')) { const s = getComputedStyle(n); out.push([s.backgroundColor, s.borderTopWidth]); n = n.parentElement; if (out.length > 4) break; }
    return out.slice(0, 4);
  });
  for (const [bg, bw] of strip.slice(0, 3)) { expect(bg).toBe("rgba(0, 0, 0, 0)"); expect(bw).toBe("0px"); }
  const tabs = await page.getByRole("tablist").first().evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, ox: getComputedStyle(el).overflowX }));
  expect(tabs.sw).toBeLessThanOrEqual(tabs.cw);
  expect(tabs.ox).not.toBe("auto");
  expect(tabs.ox).not.toBe("scroll");
});
