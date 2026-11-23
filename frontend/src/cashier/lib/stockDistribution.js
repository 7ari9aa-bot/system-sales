/**
 * توزيع الرصيد الافتتاحي على أكثر من مخزن.
 *
 * الشاشة بتعرض لكل تركيبة رقم واحد (إجمالي القطع)، والتركيبة ممكن تتقسم على أكتر من مخزن:
 * المحل 10 قطع والمخزن 30. الشغل هنا حسابي بحت (بلا شبكة): بنطلع من الإجمالي نصيب المخزن
 * الأساسي والحركات الباقية، وبنرفض أي توزيع بيزيد عن الإجمالي أو بكسر قطعة.
 */

const whole = (value) => {
  const n = Number(value ?? 0);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
};

/** المخازن النشطة اللي ينفع تركيبة تتوزّع عليها، ما عدا الأساسي. */
export function secondaryWarehouses(warehouses = [], primaryId) {
  return (warehouses ?? []).filter((w) => w && w.is_active !== false && w.id !== primaryId);
}

/** إجمالي القطع في كل التركيبات — اللي بيتكتب في «ملخص المخزون». */
export function totalOpeningStock(rows = []) {
  return rows.reduce((sum, row) => sum + whole(row.stock), 0);
}

/** نصيب مخزن معيّن من تركيبة: القيمة اللي كتبها التاجر، ومن غير مخزن أساسي مفيش توزيع. */
export function allocatedQuantity(row, warehouseId) {
  return whole(row?.alloc?.[warehouseId]);
}

/**
 * مشكلة التوزيع كرسالة عربية، أو "" لو التوزيع سليم.
 * بنقارن كل تركيبة بإجماليها: التوزيع على المخازن التانية لازم يسيب باقي للمخزن الأساسي
 * (أو يساويه بالظبط)، وممنوع يزيد عنه.
 */
export function allocationProblem(rows = [], warehouses = [], primaryId) {
  if (!primaryId) return "اختر المخزن اللي هيستلم الرصيد الافتتاحي الأول";
  const secondary = secondaryWarehouses(warehouses, primaryId);
  for (const row of rows) {
    const total = whole(row.stock);
    const taken = secondary.reduce((sum, w) => sum + allocatedQuantity(row, w.id), 0);
    if (taken > total) {
      const name = row.color && row.size ? `${row.color} / ${row.size}` : row.sku ?? "";
      return `التوزيع في ${name} أكبر من الرصيد (${taken} من ${total}). قلّل الكمية في المخازن التانية.`;
    }
  }
  return "";
}

/**
 * الخطة اللي بتتحوّل لطلبات: نصيب المخزن الأساسي لكل تركيبة، والحركات الباقية.
 * التركيبة اللي اتوزّعت بالكامل على مخازن تانية بتوصل للمخزن الأساسي بصفر (مفيش حركة فاضية).
 */
export function planOpeningDistribution(rows = [], warehouses = [], primaryId) {
  const secondary = secondaryWarehouses(warehouses, primaryId);
  const primaryStock = {};
  const movements = [];
  for (const row of rows) {
    const key = row.id ?? row.sku;
    const total = whole(row.stock);
    let taken = 0;
    for (const w of secondary) {
      const qty = allocatedQuantity(row, w.id);
      if (!qty) continue;
      taken += qty;
      movements.push({ rowId: key, sku: row.sku, warehouseId: w.id, warehouseName: w.name, quantity: qty });
    }
    // لو التوزيع زاد (شاشة قديمة أو بيانات محفوظة) بنحترم الإجمالي: الأساسي بياخد صفر والباقي اتقص.
    const rest = total - taken;
    primaryStock[key] = rest > 0 ? rest : 0;
  }
  return { primaryStock, movements, secondary };
}

/**
 * تغيير المخزن الأساسي: نصيبه الجديد لازم يكون صفر في التوزيع، ولو كان متوزّع قبل كده
 * على مخزن بقى أساسي، الكمية ترجع له كإجمالي مش كتوزيع.
 */
export function withPrimaryWarehouse(rows = [], nextPrimaryId) {
  return rows.map((row) => {
    const alloc = { ...(row.alloc ?? {}) };
    delete alloc[nextPrimaryId];
    return { ...row, alloc };
  });
}

/** وصف قصير للتوزيع يظهر جنب التركيبة: «المحل 10 · المخزن 30». */
export function allocationLabel(row, warehouses = [], primaryId) {
  const parts = [];
  const primary = (warehouses ?? []).find((w) => w.id === primaryId);
  const primaryQty = whole(row.stock) - secondaryWarehouses(warehouses, primaryId).reduce((s, w) => s + allocatedQuantity(row, w.id), 0);
  if (primaryQty > 0) parts.push(`${primary?.name ?? "المخزن الأساسي"} ${primaryQty}`);
  for (const w of secondaryWarehouses(warehouses, primaryId)) {
    const qty = allocatedQuantity(row, w.id);
    if (qty) parts.push(`${w.name} ${qty}`);
  }
  return parts.join(" · ");
}
