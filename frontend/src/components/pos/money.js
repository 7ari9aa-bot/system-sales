/** أدوات الفلوس لطبقة الكاشير — كل المبالغ نصوص Decimal زي ما الخادم بيبعتها.
 *
 * المقارنات والأحاديث كلها على scale واحد (مونيز 2) — مفيش float مقارنات
 * من غير كوانتم، وده اللي كان بيبوّظ لون الفرق في جدول المطابقة. */

/** نص فلوس للعرض — null بترجع شرطة. */
export function money(value) {
  return value == null || value === "" ? "—" : String(value);
}

/** سعر × كمية كنص مونيز. */
export function mul(priceText, qty) {
  const price = Number(priceText);
  if (!Number.isFinite(price)) return "—";
  return (price * qty).toFixed(2);
}

/** نص → رقم للقراءة بس (المصدر الصحيح دايماً نص الخادم). */
export function dec(text) {
  const n = Number(text);
  return Number.isFinite(n) ? n : 0;
}

/** هل المبلغ صفري فعلاً (بتسامح 1/2 قرش للأخطاء الطرفية). */
export function isZero(text) {
  return Math.abs(dec(text)) < 0.005;
}

/** مجموع قائمة دفعات [{amount}] كنص مونيز. */
export function sumTenders(tenders) {
  return tenders
    .reduce((acc, t) => acc + dec(t.amount), 0)
    .toFixed(2);
}

/** الفرق نصّين مونيز كنص مونيز (a − b). */
export function subMoney(a, b) {
  return (dec(a) - dec(b)).toFixed(2);
}

/** تاريخ نص ISO بتوقيت UTC كيوم — لمقارنة «وردية النهارده». */
export function utcDay(isoText) {
  if (!isoText) return null;
  return String(isoText).slice(0, 10);
}
