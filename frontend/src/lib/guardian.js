/** نظام الحارس — ضد الأخطاء الصامتة.
 *  أي فشل في النداءات أو الجافاسكريبت أو الرندر بيتسجل هنا ويظهر
 *  للمستخدم في شارة عائمة بدل ما يضيع في الكونسول. القاعدة:
 *  مفيش فشل بيتاكَت في صفيف فاضي ولا undefined بدون أثر. */

const MAX_EVENTS = 50;

let events = [];
const listeners = new Set();

export function guardianReport({ source, message, kind = "api" }) {
  const event = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    at: new Date(),
    kind, // api | window | promise | render
    source: String(source || "unknown").slice(0, 120),
    message: String(message || "Unknown failure").slice(0, 300),
  };
  // منع التكرار: نفس المصدر ونفس الرسالة في آخر 10 أحداث = تحديث آخر ظهور بس
  const dup = events
    .slice(-10)
    .find((e) => e.source === event.source && e.message === event.message);
  if (dup) {
    dup.at = event.at;
    dup.count = (dup.count ?? 1) + 1;
  } else {
    event.count = 1;
    events = [...events, event].slice(-MAX_EVENTS);
  }
  for (const cb of listeners) {
    try {
      cb(events);
    } catch {
      /* الحارس نفسه مش بيسقط التطبيق أبدًا */
    }
  }
  // أثر في الكونسول دايمًا — للتشخيص
  console.warn(`[guardian] ${event.kind} ${event.source}: ${event.message}`);
  return event;
}

export function guardianEvents() {
  return events;
}

export function guardianClear() {
  events = [];
  for (const cb of listeners) {
    try {
      cb(events);
    } catch {
      /* ignore */
    }
  }
}

export function guardianSubscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
