/**
 * جسر الماسح من تطبيق سطح المكتب: صدفة Tauri تحقن سكربت يستمع لضربات الماسح ويُطلق حدث
 * "fihrist:scan" على window — لكن فقط عندما لا يكون التركيز داخل حقل إدخال. في المتصفح العادي
 * الحدث لا يُطلق أبدًا، فكل هذا يبقى صامتًا بلا أثر.
 */
export const SCAN_EVENT_NAME = "fihrist:scan";

const handlers = new Set();
let listening = false;

function onScanEvent(event) {
  const value = String(event?.detail?.value ?? "").trim();
  if (!value) return;
  // نسخة من المجموعة حتى يستطيع المُعالج أن يُسجّل خروجه أثناء الاستدعاء نفسه.
  for (const handler of [...handlers]) handler(value);
}

/** يسجّل مُعالجًا لأكواد الماسح؛ تسجيل نفس الدالة مرتين لا يفعل شيئًا. */
export function registerScanHandler(fn) {
  if (typeof fn !== "function" || handlers.has(fn)) return;
  handlers.add(fn);
  if (!listening && typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener(SCAN_EVENT_NAME, onScanEvent);
    listening = true;
  }
}

/** يلغي تسجيل مُعالج؛ عند خروج آخر مُعالج يُرفع مستمع window نفسه. */
export function unregisterScanHandler(fn) {
  if (!handlers.delete(fn)) return;
  if (handlers.size === 0 && listening && typeof window !== "undefined" && typeof window.removeEventListener === "function") {
    window.removeEventListener(SCAN_EVENT_NAME, onScanEvent);
    listening = false;
  }
}
