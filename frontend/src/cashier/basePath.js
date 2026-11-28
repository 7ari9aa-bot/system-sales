// البادئة التي يُركَّب عليها التطبيق فعلياً: /apparel هي المسار القانوني،
// و/cashier يبقى مسار توافق لكل رابط قديم (industry-applications §11).
//
// الدوال تقرأ المسار الحالي بدل أن تفترض بادئة واحدة، فالصفحة نفسها تعمل تحت
// البادئتين ولا يقفز المستخدم من /apparel إلى /cashier عند أول ضغطة.
// الافتراضي /cashier لأن كل الروابط القديمة والاختبارات القائمة مبنية عليه،
// والمسار يُمرَّر صراحة في الاختبارات فلا تحتاج DOM.

export const APPAREL_BASE = "/apparel";
export const LEGACY_BASE = "/cashier";

function currentPath() {
  if (typeof window === "undefined" || !window.location) return "";
  return window.location.pathname || "";
}

export function appBase(pathname = currentPath()) {
  return pathname === APPAREL_BASE || pathname.startsWith(`${APPAREL_BASE}/`)
    ? APPAREL_BASE
    : LEGACY_BASE;
}

export function appPath(path = "", pathname) {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${appBase(pathname)}${suffix === "/" ? "" : suffix}`;
}
