/** شكل الكرة في كل حالة: لون، إضاءة، تشويه، سرعة دوران.
 *
 *  دالة نقية بالكامل: مدخلاتها الحالة ومستوى الصوت، ومخرجها أرقام يفهمها المشهد ثلاثي
 *  الأبعاد. الفصل مقصود — المشهد نفسه محتاج WebGL ومش بيتست في jsdom، لكن "الكرة بتنوّر
 *  لما المساعد يتكلم" قاعدة سلوك لازم تتثبت بتست عادي.
 */

/** ألوان الحالة: أخضر هادي وهو ساكت، سماوي وهو بيسمع، بنفسجي وهو بيفكر، أبيض ساخن وهو بيتكلم. */
export const ORB_STATES = {
  idle: { hue: 158, emissive: 0.35, distortion: 0.06, spin: 0.08, scale: 1 },
  opening: { hue: 172, emissive: 0.5, distortion: 0.1, spin: 0.16, scale: 1.02 },
  listening: { hue: 190, emissive: 0.6, distortion: 0.12, spin: 0.12, scale: 1.03 },
  thinking: { hue: 262, emissive: 0.7, distortion: 0.18, spin: 0.34, scale: 1.02 },
  speaking: { hue: 168, emissive: 0.95, distortion: 0.22, spin: 0.1, scale: 1.05 },
  failed: { hue: 4, emissive: 0.6, distortion: 0.05, spin: 0.04, scale: 0.98 },
};

const FALLBACK = ORB_STATES.idle;

/** الحالة اللي الكرة بتعرضها من حالة المكالمة نفسها.
 *
 *  «live» معناها المساعد شغال، لكن مين اللي بيتكلم دلوقتي؟ المستخدم ولا المساعد؟ الرقمين
 *  بيقولوا كده: مستوى المساعد الأعلى = بيتكلم، ومستوى المايك الأعلى = بيسمع.
 */
export function orbMode({ state = "idle", mic = 0, assistant = 0 } = {}) {
  if (state === "failed" || state === "refused" || state === "unavailable" || state === "not_found" || state === "closed") {
    return "failed";
  }
  if (state === "opening" || state === "requesting" || state === "connecting") return "opening";
  if (state !== "live") return "idle";
  if (assistant > 0.02 && assistant >= mic) return "speaking";
  if (mic > 0.02) return "listening";
  return "thinking";
}

/** الشكل النهائي بعد خلط الحالة بالصوت.
 *
 *  الصوت بيفتح الإضاءة والتشويه والحجم؛ الحالة بتحدد اللون والسرعة الأساسية. `smoothing`
 *  رقم بين 0 و1: 1 معناها اتبع القراءة الجديدة فوراً، والأقل معناها انتقال أنعم.
 */
export function orbLook({ state = "idle", mic = 0, assistant = 0, reduced = false } = {}) {
  const mode = orbMode({ state, mic, assistant });
  const base = ORB_STATES[mode] ?? FALLBACK;
  const energy = Math.max(clamp01(mic), clamp01(assistant));

  if (reduced) {
    return { mode, hue: base.hue, emissive: base.emissive, distortion: 0.02, spin: 0, scale: 1, glow: 0.35 };
  }

  return {
    mode,
    hue: base.hue,
    emissive: clamp01(base.emissive + energy * 0.6),
    distortion: clamp01(base.distortion + energy * 0.5),
    spin: base.spin + energy * 0.5,
    scale: base.scale + energy * 0.16,
    glow: clamp01(0.3 + energy * 0.9),
  };
}

/** تقريب تدريجي نحو هدف: بيخلي الحركة ناعمة بدل ما تنطط مع كل حزمة صوت. */
export function approach(current, target, alpha = 0.18) {
  const a = clamp01(alpha);
  return current + (target - current) * a;
}

export function clamp01(value) {
  const n = Number.isFinite(value) ? value : 0;
  return Math.min(1, Math.max(0, n));
}

/** تقييد رقم بين -1 و1، وأي قيمة غلط بتبقى صفر بدل ما تكسر المشهد. */
export function clampSigned(value) {
  const n = Number.isFinite(value) ? value : 0;
  return Math.max(-1, Math.min(1, n));
}

/** سحب الماوس بيلف المشهد: بنحوّل حركة البكسل لزاوية مقيّدة، والسحب بيتراكم
 *  عشان لفة كاملة بالماوس تعني لفة كاملة بالكاميرا. */
export function dragDelta({ dx = 0, dy = 0, width = 1, height = 1, current = { x: 0, y: 0 } } = {}) {
  const stepX = Number.isFinite(dx) ? (dx / Math.max(1, width)) * 2.6 : 0;
  const stepY = Number.isFinite(dy) ? (dy / Math.max(1, height)) * 2.6 : 0;
  return {
    x: clampSigned((current?.x ?? 0) + stepX),
    y: clampSigned((current?.y ?? 0) + stepY),
  };
}

/** موضع الكاميرا: الصفحة كلها بتتحرك، مش الكرة بس.
 *
 *  المؤشر بيلف الكاميرا حوالين المشهد، والسحب بيلفها أكتر، والصوت بيقرّبها. الكاميرا
 *  قاعدة فوق مركز المشهد شوية وبتطّلع لتحت، فالنجوم والحلقات والأرضية كلهم داخل الكادر —
 *  الشاشة كلها بقيت عالم 3D مش خلفية سوداء حوالين كرة.
 */
export function cameraRig({ pointerX = 0, pointerY = 0, energy = 0, time = 0, dragX = 0, dragY = 0 } = {}) {
  const px = clampSigned(pointerX);
  const py = clampSigned(pointerY);
  const dx = clampSigned(dragX);
  const dy = clampSigned(dragY);
  const e = clamp01(energy);
  const t = Number.isFinite(time) ? time : 0;
  // تنفّس بطيء في السكون: الكاميرا بتتحرك حتى من غير صوت، بس بمسافة صغيرة جداً.
  const drift = Math.sin(t * 0.25) * 0.06;
  return {
    x: px * 0.9 + dx * 1.5 + drift,
    y: 0.62 + py * 0.4 + dy * 0.8 + Math.cos(t * 0.19) * 0.05,
    z: 5.6 - e * 0.7 - Math.abs(dx) * 0.35,
    lookY: -0.22 + py * 0.2 - dy * 0.35,
  };
}
