// فحص الحارس بمتصفح فعلي — يشغَّل والسيرفر المحلي على :3000
import { chromium } from "playwright-core";

const BASE = "http://localhost:3000";
const results = [];
const ok = (name, pass, extra = "") => {
  results.push(`${pass ? "PASS" : "FAIL"} ${name}${extra ? " — " + extra : ""}`);
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message.slice(0, 120)));

// 1) اللوجين: الشارة موجودة والصفحة بتترندر وصفر أخطاء
await page.goto(`${BASE}/login`, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(600);
const chip1 = (await page.textContent("button:has-text('الحارس')").catch(() => null)) || "";
ok("guardian chip visible on login", chip1.includes("الحارس"), chip1.trim());
ok("login renders", ((await page.textContent("body")) || "").includes("مرحباً بعودتك"));
ok("no render errors on login", pageErrors.length === 0, pageErrors[0] || "");

// 2) دخول فعلي → الداشبورد يرسم بياناته وصفر أخطاء
await page.fill("input[type=email], #email", "test@fihrist.app");
await page.fill("input[type=password], #password", "whatever123");
await page.click("button[type=submit]");
await page.waitForURL("**/dashboard", { timeout: 15000 });
await page.waitForFunction(() => document.body.innerText.includes("EGP"), null, { timeout: 15000 });
ok("dashboard paints data after login", true, page.url());
ok("no render errors on dashboard", pageErrors.length === 0, pageErrors[0] || "");

// 3) اصطياد فشل صامت: استنى انتهاء TTL الكاش (20 ث) عشان الاعتراض يمسك
//    إعادة التحقق، هزّ الصفحة — الحارس لازم يحمرّ بالعدّاد
await page.waitForTimeout(21_000);
await page.route("**/api/v1/ai/agents*", (route) => route.abort("failed"));
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);
const chipAfter = (await page.textContent("button:has-text('الحارس')").catch(() => "")) || "";
ok("guardian catches silent failure", /الحارس\s*·\s*[1-9]/.test(chipAfter), chipAfter.trim());

// 4) اللوحة بتورّي تفاصيل الوقعة
if (/·/.test(chipAfter)) {
  await page.click("button:has-text('الحارس')");
  await page.waitForTimeout(300);
  const panel = (await page.textContent("body")) || "";
  ok("failure details visible in panel", panel.includes("ai/agents"));
}

await page.unroute("**/api/v1/ai/agents*");
console.log(results.join("\n"));
console.log("pageerrors total:", pageErrors.length);
await page.screenshot({ path: "test-results/guardian-smoke.png" });
await browser.close();
const failed = results.filter((r) => r.startsWith("FAIL")).length;
process.exit(failed ? 1 : 0);
