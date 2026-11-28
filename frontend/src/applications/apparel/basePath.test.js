// البادئة القانونية للتطبيق هي /apparel، والقديم /cashier يبقى يعمل.
// الاختبار يثبت أن التطبيق مركَّب على البادئتين، وأن الروابط الداخلية تتبع
// البادئة التي فُتح بها المستخدم بدل أن تقفز إلى المسار القديم.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { APPAREL_BASE, LEGACY_BASE, appBase, appPath } from "./basePath";

describe("appBase", () => {
  it("follows the canonical prefix when the app is open under /apparel", () => {
    expect(appBase("/apparel/pos")).toBe(APPAREL_BASE);
    expect(appPath("/products", "/apparel/pos")).toBe("/apparel/products");
  });

  it("keeps every legacy link under /cashier", () => {
    expect(appBase("/cashier/pos")).toBe(LEGACY_BASE);
    expect(appPath("inventory", "/cashier/pos")).toBe("/cashier/inventory");
  });

  it("defaults to the legacy prefix outside both mounts", () => {
    expect(appBase("/dashboard")).toBe(LEGACY_BASE);
  });
});

describe("routing", () => {
  it("mounts the apparel app on both prefixes", () => {
    const app = readFileSync(resolve(process.cwd(), "src/App.jsx"), "utf8");
    expect(app).toContain('path="/apparel/*"');
    expect(app).toContain('path="/cashier/*"');
  });
});
