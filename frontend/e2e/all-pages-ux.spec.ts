import { test, expect, type Page } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang } from "./support";

const SCREENSHOT_DIR = "C:/Users/CS/.gemini/antigravity-ide/brain/5092f33b-d50c-4435-9700-8627e10473a8/screenshots";

/** Generic fallback for dashboard APIs to prevent uncaught 500s or infinite loaders */
async function mockAllDashboardApis(page: Page) {
  await mockShell(page);

  // Catch-all for any other /api/v1 routes (registered first so specific routes below override it)
  await page.route("**/api/v1/**", (route) => {
    if (!route.request().isNavigationRequest()) {
      return json(route, { items: [], total: 0, status: "ok" });
    }
    return route.continue();
  });

  // Tenant currency
  await page.route("**/api/v1/tenants/*/currency", (route) =>
    json(route, { tenant_id: "tenant-1", currency: "EGP" })
  );

  // Platform Diagnostics (Anti-Silent-Failures)
  await page.route("**/api/v1/platform/diagnostics*", (route) => {
    const url = route.request().url();
    if (url.includes("/remediate")) {
      return json(route, {
        success: true,
        message_ar: "تم فحص وإصلاح 2 أحداث معلقة بنجاح",
        message_en: "Successfully scanned and remediated 2 pending events",
        actions_taken: ["إعادة جدولة 2 أحداث عالقة في Outbox", "تنظيف أقفال المزامنة"],
        reclaimed_outbox_events: 2,
        timestamp: new Date().toISOString(),
      });
    }
    return json(route, {
      overall_status: "healthy",
      summary_ar: "جميع الأنظمة تعمل بكفاءة تامة وبدون أي فشل صامت",
      summary_en: "All subsystems operational with zero silent failures",
      total_checks: 6,
      passed_checks: 6,
      issues_count: 0,
      timestamp: new Date().toISOString(),
      checks: [
        {
          id: "db-1",
          category: "infrastructure",
          name_ar: "قاعدة البيانات الرئيسية",
          name_en: "Primary Database (PostgreSQL)",
          status: "healthy",
          latency_ms: 1.2,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { active_connections: 5, pool_size: 20 },
          timestamp: new Date().toISOString(),
        },
        {
          id: "redis-1",
          category: "infrastructure",
          name_ar: "خادم التخزين المؤقت",
          name_en: "Redis Cache & Queue",
          status: "healthy",
          latency_ms: 0.8,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { ping: "ok", memory_used: "42MB" },
          timestamp: new Date().toISOString(),
        },
        {
          id: "outbox-1",
          category: "messaging",
          name_ar: "صندوق الأحداث والمزامنة",
          name_en: "Transactional Outbox",
          status: "healthy",
          latency_ms: 2.1,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { pending_events: 0, stranded_events: 0 },
          timestamp: new Date().toISOString(),
        },
        {
          id: "dlq-1",
          category: "messaging",
          name_ar: "طابور الرسائل المتعثرة",
          name_en: "Dead Letter Queue (DLQ)",
          status: "healthy",
          latency_ms: 1.5,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { dead_letters: 0 },
          timestamp: new Date().toISOString(),
        },
        {
          id: "ai-1",
          category: "ai",
          name_ar: "خدمة نماذج الذكاء الاصطناعي",
          name_en: "AI Agent Orchestration",
          status: "healthy",
          latency_ms: 18.5,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { provider: "gemini-2.5-flash", active_agents: 2 },
          timestamp: new Date().toISOString(),
        },
        {
          id: "integrity-1",
          category: "data_integrity",
          name_ar: "سلامة البيانات والعملات",
          name_en: "Data Integrity & Currency Invariants",
          status: "healthy",
          latency_ms: 3.5,
          error: null,
          root_cause: null,
          remediation: null,
          metrics: { orphaned_records: 0 },
          timestamp: new Date().toISOString(),
        },
      ],
    });
  });

  // Health indicator
  await page.route("**/api/v1/platform/health", (route) =>
    json(route, {
      status: "healthy",
      subsystems: [
        { name: "database", status: "healthy", latency_ms: 1.2, detail: "PostgreSQL 16.2 متصل ومستقر" },
        { name: "redis", status: "healthy", latency_ms: 0.8, detail: "Redis 7.2 ping ok" },
        { name: "outbox", status: "healthy", latency_ms: 2.1, detail: "0 أحداث معلقة" },
      ],
    })
  );

  // Analytics / Dashboard
  await page.route("**/api/v1/analytics/dashboard", (route) =>
    json(route, {
      orders: {
        orders_count: 142,
        gross_revenue: 85400,
        refunded_amount: 1200,
        net_revenue: 84200,
        refund_excess: 0,
        gross_aov: 601.4,
        net_aov: 592.9,
        currency: "EGP",
        timezone: "Africa/Cairo",
      },
      ai_orders_30d: 48,
      conversations: { open: 12, unread: 4 },
      customers: 320,
      products_active: 45,
      low_stock_count: 3,
      out_of_stock_count: 1,
      low_stock_threshold: 5,
      daily_orders: [
        { day: "2026-09-22", orders: 18, gross_revenue: 11000, refunded_amount: 0, net_revenue: 11000, refund_excess: 0 },
        { day: "2026-09-23", orders: 22, gross_revenue: 14200, refunded_amount: 0, net_revenue: 14200, refund_excess: 0 },
        { day: "2026-09-24", orders: 25, gross_revenue: 16500, refunded_amount: 500, net_revenue: 16000, refund_excess: 0 },
        { day: "2026-09-25", orders: 19, gross_revenue: 12000, refunded_amount: 0, net_revenue: 12000, refund_excess: 0 },
        { day: "2026-09-26", orders: 28, gross_revenue: 18000, refunded_amount: 700, net_revenue: 17300, refund_excess: 0 },
        { day: "2026-09-27", orders: 30, gross_revenue: 13700, refunded_amount: 0, net_revenue: 13700, refund_excess: 0 },
      ],
      revenue_by_source: [
        { source: "whatsapp", revenue: 52000, conversions: 84 },
        { source: "facebook", revenue: 22000, conversions: 38 },
        { source: "direct", revenue: 10200, conversions: 20 },
      ],
    })
  );

  // Operations / My Work
  await page.route("**/api/v1/operations/my-work", (route) =>
    json(route, {
      items: [
        { id: "task-1", title: "مراجعة طلب رقم #1042", kind: "review", status: "pending", priority: "high", due_at: "2026-09-29T10:00:00Z" },
        { id: "task-2", title: "تأكيد شحن طلب قيد الانتظار", kind: "shipping", status: "pending", priority: "medium", due_at: "2026-09-29T14:00:00Z" },
      ],
      total: 2,
    })
  );

  // Conversations / Inbox
  await page.route("**/api/v1/conversations*", (route) => {
    return json(route, {
      items: [
        {
          id: "conv-1",
          customer_name: "أحمد محمود",
          last_message: "هل المنتج متوفر بلون أسود؟",
          channel: "whatsapp",
          unread_count: 1,
          updated_at: "2026-09-28T16:30:00Z",
          status: "open",
        },
        {
          id: "conv-2",
          customer_name: "سارة خليل",
          last_message: "تم استلام الطلب شكرًا لكم!",
          channel: "facebook",
          unread_count: 0,
          updated_at: "2026-09-28T15:10:00Z",
          status: "closed",
        },
      ],
      total: 2,
    });
  });

  // Customers
  await page.route("**/api/v1/customers*", (route) => {
    return json(route, {
      items: [
        { id: "cust-1", name: "أحمد محمود", phone: "+201012345678", email: "ahmed@example.com", total_orders: 5, total_spent: 3200, status: "active", is_lead: false },
        { id: "cust-2", name: "مريم حسن", phone: "+201098765432", email: "mariam@example.com", total_orders: 1, total_spent: 450, status: "lead", is_lead: true },
      ],
      total: 2,
    });
  });

  // Orders
  await page.route("**/api/v1/orders*", (route) => {
    return json(route, {
      items: [
        { id: "ord-1", order_number: "ORD-1001", customer_name: "أحمد محمود", total_amount: 850, currency: "EGP", status: "delivered", created_at: "2026-09-28T12:00:00Z", items_count: 2 },
        { id: "ord-2", order_number: "ORD-1002", customer_name: "محمود سامي", total_amount: 1400, currency: "EGP", status: "pending", created_at: "2026-09-28T14:30:00Z", items_count: 3 },
      ],
      total: 2,
    });
  });

  // Products
  await page.route("**/api/v1/catalog/products*", (route) => {
    return json(route, {
      items: [
        { id: "prod-1", name: "سماعات بلوتوث برو", sku: "AUDIO-PRO-1", price: 650, currency: "EGP", status: "active", stock: 24 },
        { id: "prod-2", name: "شاحن سريع 65 واط", sku: "CHG-65W-BLK", price: 280, currency: "EGP", status: "active", stock: 8 },
      ],
      total: 2,
    });
  });

  // Inventory
  await page.route("**/api/v1/inventory*", (route) => {
    return json(route, {
      items: [
        { id: "inv-1", product_name: "سماعات بلوتوث برو", sku: "AUDIO-PRO-1", available_quantity: 24, reserved_quantity: 2, low_stock_threshold: 5 },
        { id: "inv-2", product_name: "شاحن سريع 65 واط", sku: "CHG-65W-BLK", available_quantity: 8, reserved_quantity: 0, low_stock_threshold: 10 },
      ],
      total: 2,
    });
  });

  // Marketing
  await page.route("**/api/v1/marketing*", (route) => {
    return json(route, {
      campaigns: [
        { id: "camp-1", name: "عروض نهاية الأسبوع", channel: "whatsapp", status: "active", sent_count: 1200, conversion_rate: 4.8 },
      ],
      total: 1,
    });
  });

  // AI
  await page.route("**/api/v1/ai*", (route) => {
    return json(route, {
      agents: [
        { id: "agent-sales", name: "مساعد المبيعات الذكي", model: "gemini-2.5-flash", system_prompt: "أنت مساعد مبيعات محترف ومتعاون...", temperature: 0.7, active: true },
      ],
    });
  });

  // Financial
  await page.route("**/api/v1/financial*", (route) => {
    return json(route, {
      revenue: { gross: 85400, net: 84200, refunds: 1200, currency: "EGP" },
      invoices: [],
      items: [],
      total: 0,
    });
  });

  // Approvals
  await page.route("**/api/v1/authority/approvals*", (route) => {
    return json(route, {
      items: [],
      total: 0,
    });
  });

  // Settings / Team
  await page.route("**/api/v1/identity/users*", (route) => {
    return json(route, {
      items: [
        { id: "user-1", email: "owner@example.com", full_name: "مالك المتجر", role: "owner", active: true },
      ],
      total: 1,
    });
  });

  // Notifications
  await page.route("**/api/v1/notifications**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/unread-count")) return json(route, { count: 0 });
    if (path.endsWith("/summary")) return json(route, { total: 0, unread: 0, by_kind: [] });
    return json(route, []);
  });
}

test.describe("UX & Page Verification Suite", () => {
  test("1. Public Pages Render Correctly", async ({ page }) => {
    test.setTimeout(180_000);
    await seedLang(page, "ar");

    const publicPages = [
      { path: "/", name: "landing" },
      { path: "/pricing", name: "pricing" },
      { path: "/privacy", name: "privacy" },
      { path: "/terms", name: "terms" },
      { path: "/product", name: "product" },
      { path: "/security", name: "security" },
      { path: "/assistant", name: "assistant" },
      { path: "/automation", name: "automation" },
      { path: "/context", name: "context" },
      { path: "/conversations", name: "conversations" },
    ];

    for (const p of publicPages) {
      await page.goto(p.path);
      const errorBoundary = page.locator("text=عذرًا، حدث خطأ غير متوقع");
      await expect(errorBoundary).not.toBeVisible();
      await page.screenshot({
        path: `${SCREENSHOT_DIR}/public_${p.name}.png`,
        fullPage: false,
      });
    }
  });

  test("2. Auth Pages and Redirect Routes", async ({ page }) => {
    test.setTimeout(180_000);
    await seedLang(page, "ar");

    // A) Auth login page (unauthenticated)
    await page.goto("/auth/login");
    await expect(page.getByTestId("auth-login-card")).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/auth_login.png` });

    // B) Auth signup page (unauthenticated)
    await page.goto("/auth/signup");
    await expect(page.locator("h1")).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/auth_signup.png` });

    // C) /login redirects to /auth/login
    await page.goto("/login");
    await expect(page).toHaveURL(/\/auth\/login$/);

    // Authenticated redirects:
    await seedAuth(page);
    await mockAllDashboardApis(page);
    await page.evaluate(() => {
      window.localStorage.setItem(
        "sales_os_tokens",
        JSON.stringify({ access_token: "test-access-token", refresh_token: "test-refresh-token" })
      );
    });

    // D) /my-work redirects to /dashboard
    await page.goto("/my-work");
    await expect(page).toHaveURL(/\/dashboard$/);

    // E) /tasks redirects to /dashboard
    await page.goto("/tasks");
    await expect(page).toHaveURL(/\/dashboard$/);

    // F) /leads redirects to /customers?filter=lead
    await page.goto("/leads");
    await expect(page).toHaveURL(/\/customers\?filter=lead$/);
  });

  test("3. Core Business & Operations Dashboard Pages", async ({ page }) => {
    test.setTimeout(240_000);
    await seedAuth(page);
    await seedLang(page, "ar");
    await mockAllDashboardApis(page);

    const businessPages = [
      { path: "/dashboard", name: "01_overview" },
      { path: "/inbox", name: "02_inbox" },
      { path: "/customers", name: "03_customers" },
      { path: "/orders", name: "04_orders" },
      { path: "/products", name: "05_products" },
      { path: "/inventory", name: "06_inventory" },
      { path: "/marketing", name: "07_marketing" },
      { path: "/financial", name: "08_financial" },
      { path: "/ai", name: "09_ai" },
      { path: "/analytics", name: "10_analytics" },
      { path: "/approvals", name: "11_approvals" },
      { path: "/diagnostics", name: "12_diagnostics" },
      { path: "/settings", name: "13_settings" },
      { path: "/team", name: "14_team" },
      { path: "/operations", name: "15_operations" },
      { path: "/sla", name: "16_sla" },
      { path: "/queues", name: "17_queues" },
      { path: "/decisions", name: "18_decisions" },
      { path: "/effects", name: "19_effects" },
      { path: "/journeys", name: "20_journeys" },
      { path: "/live", name: "21_live" },
      { path: "/notifications", name: "22_notifications" },
    ];

    for (const p of businessPages) {
      await page.goto(p.path);

      // Wait for Shell hydration and main content
      await expect(page.getByTestId("nav-overview")).toBeVisible({ timeout: 15_000 });

      // Verify no Error Boundary
      const errorFallback = page.locator("text=حدث خطأ غير متوقع");
      await expect(errorFallback).not.toBeVisible();

      // Check RTL direction
      const htmlDir = await page.getAttribute("html", "dir");
      expect(htmlDir).toBe("rtl");

      // Take clean, fully rendered screenshot
      await page.screenshot({
        path: `${SCREENSHOT_DIR}/dash_${p.name}.png`,
        fullPage: false,
      });
    }
  });

  test("4. Interactive UX: Health Indicator, Diagnostics & Theme", async ({ page }) => {
    test.setTimeout(180_000);
    await seedAuth(page);
    await seedLang(page, "ar");
    await mockAllDashboardApis(page);
    await page.goto("/dashboard");

    // Wait for Shell to be ready and mounted
    await expect(page.getByTestId("nav-overview")).toBeVisible({ timeout: 15_000 });

    // A) Health Indicator dropdown
    const healthBadge = page.getByTestId("health-indicator");
    await expect(healthBadge).toBeVisible();
    await healthBadge.click();

    // Verify dropdown content contains link to diagnostics
    const diagLink = page.getByTestId("health-open-diagnostics");
    await expect(diagLink).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_01_health_dropdown.png` });

    // Navigate to Diagnostics via the indicator link
    await diagLink.click();
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/diagnostics$/);

    // Diagnostics Center UX
    await expect(page.locator("h1:has-text('مركز التشخيص والفحص الشامل')")).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_02_diagnostics_page.png` });

    // Test "إصلاح تلقائي" button
    const autoRemediateBtn = page.getByTestId("diagnostics-remediate-btn");
    await expect(autoRemediateBtn).toBeVisible();
    await autoRemediateBtn.click();

    // Verify result card appeared
    await expect(page.locator("text=نتيجة الإصلاح التلقائي")).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_03_remediation_done.png` });

    // Test Theme Toggle (Dark / Light)
    const themeBtn = page.getByTestId("theme-toggle");
    await expect(themeBtn).toBeVisible();
    await themeBtn.click();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_04_theme_dark.png` });
    await themeBtn.click();

    // Test Language Toggle (AR / EN)
    const langBtn = page.getByTestId("lang-toggle");
    await expect(langBtn).toBeVisible();
    await langBtn.click();
    await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_05_lang_en.png` });
    await langBtn.click();

    // Test Command Palette (Ctrl+K)
    await page.keyboard.press("Control+k");
    const palette = page.getByTestId("command-palette");
    if (await palette.isVisible()) {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/interactive_06_command_palette.png` });
      await page.keyboard.press("Escape");
    }
  });
});
