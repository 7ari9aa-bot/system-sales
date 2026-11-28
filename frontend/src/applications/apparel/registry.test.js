// سجل الواجهة لازم يطابق سجل الـBackend حرفياً.
//
// الاختبار يقرأ ملفات البايثون الفعلية بدل تكرار القائمة: لو أضاف الـBackend شاشة
// ولم تُضف هنا، أو أعلنت الواجهة صلاحية غير موجودة، يفشل الاختبار بدل أن تظهر
// شاشة بلا صلاحية أو صلاحية بلا شاشة (industry-applications §11 و§14).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  APPAREL,
  SHELL,
  apparelPaths,
  apparelScreens,
  canSeeScreen,
  visibleScreens,
} from "./registry";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../..");
const backendRoutes = readFileSync(
  resolve(repo, "backend/app/applications/apparel/routes.py"),
  "utf8",
);
const backendPermissions = readFileSync(
  resolve(repo, "backend/app/applications/apparel/permissions.py"),
  "utf8",
);
const appJsx = readFileSync(resolve(repo, "frontend/src/App.jsx"), "utf8");

function backendRoutePaths() {
  return [...backendRoutes.matchAll(/ApparelRoute\("(\/apparel[^"]*)"/g)].map((m) => m[1]);
}

function backendPermissionCodes() {
  // الصلاحيات الطويلة يكسّرها المنسّق على أسطر، فالمطابقة تسمح بمسافة أو سطر جديد.
  return [...backendPermissions.matchAll(/ApparelPermission\(\s*"([a-z_.]+)"/g)].map((m) => m[1]);
}

function backendModuleKeys() {
  const manifest = readFileSync(
    resolve(repo, "backend/app/applications/apparel/manifest.py"),
    "utf8",
  );
  return [...manifest.matchAll(/key="([a-z]+)",\n\s+title_ar=/g)].map((m) => m[1]);
}

describe("سجل تطبيق الملابس", () => {
  it("يعرّف التطبيق بمفتاح وقطاع صحيحين", () => {
    expect(APPAREL.key).toBe("apparel");
    expect(APPAREL.industry).toBe("apparel");
    expect(APPAREL.entrypoint.startsWith("/apparel")).toBe(true);
  });

  it("يعلن نفس شاشات الـBackend بلا زيادة ولا نقصان", () => {
    expect([...apparelPaths].sort()).toEqual([...backendRoutePaths()].sort());
  });

  it("لا يعلن صلاحية غير موجودة في سجل الـBackend", () => {
    const known = new Set(backendPermissionCodes());
    const unknown = apparelScreens
      .map((screen) => screen.permission)
      .filter((code) => code && !known.has(code));
    expect(unknown).toEqual([]);
  });

  it("ينسب كل شاشة لوحدة معلنة في الـManifest", () => {
    const modules = new Set([...backendModuleKeys(), SHELL]);
    const orphans = apparelScreens
      .filter((screen) => !modules.has(screen.module))
      .map((screen) => `${screen.path} -> ${screen.module}`);
    expect(orphans).toEqual([]);
  });

  it("يشير إلى مسارات موجودة فعلاً في App.jsx", () => {
    const missing = apparelScreens
      .map((screen) => screen.currentPath)
      .filter((path) => {
        const first = path.split("/")[1];
        return !(
          appJsx.includes(`path="${path}"`) ||
          appJsx.includes(`path="/${first}/*"`) ||
          appJsx.includes(`path="/${first}"`)
        );
      });
    expect(missing).toEqual([]);
  });

  it("يخفي الشاشة عن من لا يملك صلاحيتها ولا يخفي غيرها", () => {
    const pos = apparelScreens.find((screen) => screen.path === "/apparel/pos");
    expect(canSeeScreen(pos, ["apparel.pos.access"])).toBe(true);
    expect(canSeeScreen(pos, [])).toBe(false);

    const visible = visibleScreens(["apparel.pos.access"]).map((screen) => screen.path);
    expect(visible).toContain("/apparel/pos");
    expect(visible).toContain("/apparel/settings");
    expect(visible).not.toContain("/apparel/products");
  });
});
