/**
 * حارس الحفظ: ضغطة واحدة = طلب واحد.
 *
 * على اتصال بطيء التاجر بيدوس «حفظ» تاني لأنه فاكر إن مفيش حاجة حصلت، فيطلع منتجين
 * بنفس الاسم (وSKU مكرر). الحارس بيرفض أي نداء تاني لحد ما الأول يخلص، ويرجّع نفس الوعد.
 */
export function createSaveGuard(save) {
  let inFlight = null;
  return function guarded(...args) {
    if (inFlight) return inFlight;
    inFlight = (async () => {
      try {
        return await save(...args);
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  };
}

/** حالة الزرار أثناء الحفظ: مقفول ومكتوب عليه إن الحفظ شغّال. */
export function saveButtonState({ canSave = true, isSaving = false } = {}) {
  return {
    disabled: !canSave || isSaving,
    label: isSaving ? "جاري الحفظ…" : "حفظ المنتج",
  };
}
