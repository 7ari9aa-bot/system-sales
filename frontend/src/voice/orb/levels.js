/** قياس الصوت اللي بيحرّك الكرة.
 *
 *  مصدران: المايك (PCM16 بيتبعت للسيرفر) وصوت المساعد (PCM16 راجع من السوكت). الاتنين
 *  بيعدّوا من نفس الدالة، فاللي بيحرّك الكرة هو الصوت الحقيقي مش مؤقّت بيقلّد الكلام.
 */
import { clamp01 } from "./looks";

/** جذر متوسط المربعات لعيّنة PCM16، مقيّد بين 0 و1.
 *
 *  PCM16 مداها ±32768، فبنقسم على 32768. الأرقام الغنائية عادة أقل من 0.3، فبنضرب في
 *  4 ونقصّ عند 1 عشان الحركة تبان من أول صوت عادي مش عند الصراخ.
 */
export function pcm16Level(buffer) {
  if (!buffer || typeof buffer.byteLength !== "number" || buffer.byteLength < 2) return 0;
  const samples = new Int16Array(buffer);
  const count = samples.length;
  if (!count) return 0;
  let sum = 0;
  for (let i = 0; i < count; i += 1) {
    const v = samples[i] / 32768;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / count);
  return clamp01(rms * 4);
}

/** مستوى من مصفوفة أرقام عائمة (ScriptProcessor بيدي Float32). */
export function float32Level(samples) {
  if (!samples || !samples.length) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const v = samples[i] ?? 0;
    sum += v * v;
  }
  return clamp01(Math.sqrt(sum / samples.length) * 4);
}

/** عدّاد مستويات مشترك: المكالمة بتكتب فيه، والكرة بتقرأ منه في كل فريم.
 *
 *  مش React state عن قصد — الصوت بيوصل 20 مرة في الثانية، وكل تحديث state معناه إعادة
 *  رسم للشجرة كلها. الكرة بتقرأ الأرقام في حلقة الرسم بتاعتها بدل كده.
 */
export function createLevelMeter() {
  let mic = 0;
  let assistant = 0;
  let micAt = 0;
  let assistantAt = 0;
  return {
    setMic(level, now = Date.now()) {
      mic = clamp01(level);
      micAt = now;
    },
    setAssistant(level, now = Date.now()) {
      assistant = clamp01(level);
      assistantAt = now;
    },
    /** المستوى الحالي، وبيتصفّر لو الصوت وقف من أكتر من `decayMs` — السكوت جزء من الحالة. */
    read(now = Date.now(), decayMs = 220) {
      return {
        mic: now - micAt > decayMs ? 0 : mic,
        assistant: now - assistantAt > decayMs ? 0 : assistant,
      };
    },
  };
}
