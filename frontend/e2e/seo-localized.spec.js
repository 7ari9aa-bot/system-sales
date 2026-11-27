import { expect, test } from "@playwright/test";

const ORIGIN = "https://fihrist.world";

test("English home is English, self-canonical and linked to its Arabic twin", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const response = await page.goto("/eg/en", { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBe(200);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("h1")).toContainText("From customer conversation to");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `${ORIGIN}/eg/en`);
  await expect(page.locator('link[rel="alternate"][hreflang="ar-EG"]')).toHaveAttribute("href", `${ORIGIN}/eg/ar`);
  await expect(page.locator('link[rel="alternate"][hreflang="en-EG"]')).toHaveAttribute("href", `${ORIGIN}/eg/en`);
  await expect(page.locator('link[rel="alternate"][hreflang="x-default"]')).toHaveAttribute("href", `${ORIGIN}/`);

  // A saved Arabic preference must not override the URL.
  await page.evaluate(() => localStorage.setItem("fh_locale", "ar"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  // Marketing links stay inside /eg/en, app links are untouched.
  const hrefs = await page.locator("header a[href], footer a[href]").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  expect(hrefs).toContain("/eg/en/pricing");
  expect(hrefs).toContain("/login");
  expect(hrefs.filter((h) => /^\/(en|pricing|product|security)(\/|$)/.test(h))).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test("a Saudi page keeps its visitor in Saudi Arabia", async ({ page }) => {
  await page.goto("/sa/en/pricing", { waitUntil: "domcontentloaded" });
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `${ORIGIN}/sa/en/pricing`);
  const hrefs = await page.locator("header a[href], footer a[href]").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  expect(hrefs).toContain("/sa/en/pricing");
  expect(hrefs.filter((h) => h.startsWith("/eg/"))).toEqual([]);

  await page.getByTestId("button-toggle-language").click();
  await expect(page).toHaveURL(/\/sa\/ar\/pricing$/);
});

test("language switch moves to the matching page in the other language", async ({ page }) => {
  await page.goto("/eg/en/solutions/whatsapp-sales-system", { waitUntil: "domcontentloaded" });
  await page.getByTestId("button-toggle-language").click();
  await expect(page).toHaveURL(/\/eg\/ar\/solutions\/whatsapp-sales-system$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");

  await page.getByTestId("button-toggle-language").click();
  await expect(page).toHaveURL(/\/eg\/en\/solutions\/whatsapp-sales-system$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("every keyword landing page renders a distinct H1, FAQ and FAQ schema in both languages", async ({ page }) => {
  const slugs = [
    "whatsapp-sales-system", "inventory-management-system", "ai-sales-assistant", "unified-inbox",
    "pos-cashier-system", "sales-crm-for-stores", "order-management-system",
  ];
  const headings = new Set();
  for (const prefix of ["/eg/ar", "/eg/en"]) {
    for (const slug of slugs) {
      const response = await page.goto(`${prefix}/solutions/${slug}`, { waitUntil: "domcontentloaded" });
      expect(response?.status(), `${prefix}/solutions/${slug}`).toBe(200);
      headings.add(await page.locator("h1").first().innerText());
      expect(await page.locator("details.faq-item").count()).toBeGreaterThanOrEqual(4);
      const schemas = await page.locator('script[type="application/ld+json"]').allInnerTexts();
      expect(schemas.some((s) => s.includes('"FAQPage"'))).toBe(true);
    }
  }
  expect(headings.size).toBe(slugs.length * 2);
});

test("blog index and articles render in both languages with FAQ and schema", async ({ page }) => {
  for (const [prefix, lang] of [["/eg/ar", "ar"], ["/eg/en", "en"]]) {
    const index = await page.goto(`${prefix}/blog`, { waitUntil: "domcontentloaded" });
    expect(index?.status()).toBe(200);
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    expect(await page.locator('a[href*="/blog/"]').count()).toBeGreaterThanOrEqual(10);

    const response = await page.goto(`${prefix}/blog/how-to-sell-on-whatsapp-organized`, { waitUntil: "domcontentloaded" });
    expect(response?.status()).toBe(200);
    // The article mounts after the shell: counting on domcontentloaded read an empty article and
    // reported 0 headings while the snapshot taken seconds later showed twelve.
    await expect(page.locator("article h2").first()).toBeVisible();
    expect(await page.locator("article h2").count()).toBeGreaterThanOrEqual(7);
    expect(await page.locator("details.faq-item").count()).toBeGreaterThanOrEqual(4);
    const schemas = (await page.locator('script[type="application/ld+json"]').allInnerTexts()).join("");
    expect(schemas).toContain('"Article"');
    expect(schemas).toContain('"FAQPage"');
  }
  expect((await page.goto("/eg/ar/blog/unknown-post"))?.status()).toBe(404);
});
