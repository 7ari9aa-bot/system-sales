// Stock ledger rows (GET /inventory/movements) -> what the movements screens show.
//
// The ledger mixes two different things, and showing both as "in/out" would mislead:
//  * PHYSICAL movements change on_hand (purchase, sale, return, adjustment, supplier return ...).
//  * AVAILABILITY rows (reservation hold / release) only move `reserved`; no goods moved.
// And a stocktake `adjust` row stores the NEW COUNT in `quantity`, not a difference, so its real
// effect is balance_after minus the previous balance of the same variant+warehouse.

export const AVAILABILITY_REASONS = new Set(["reservation", "reservation_release"]);

export const REASON_LABEL = {
  purchase: "شراء",
  sale: "بيع",
  return: "مرتجع عميل",
  adjustment: "تسوية جرد",
  supplier_return: "مرتجع لمورد",
  supplier_return_reversal: "إلغاء مرتجع مورد",
  transfer_in: "تحويل وارد",
  transfer_out: "تحويل صادر",
  damage: "تالف",
  reservation: "حجز",
  reservation_release: "فك حجز",
};

export const reasonLabel = (reason) => REASON_LABEL[reason] ?? reason ?? "—";

export const isPhysical = (row) => !AVAILABILITY_REASONS.has(row.reason);

/**
 * Map ledger rows (newest first, as the server returns them) to screen rows.
 * `in`/`out` are the signed effect on on_hand; for `adjust` it is derived from the neighbouring row of
 * the same variant+warehouse. When that earlier row is not in the loaded window the effect is unknown
 * (null), never guessed.
 */
export function movementsFromApi(raw) {
  const list = Array.isArray(raw) ? raw : [];
  const physical = list.filter(isPhysical);
  const previousBalance = new Map(); // row id -> balance_after of the older row of the same stock position
  const lastSeen = new Map();
  for (let i = physical.length - 1; i >= 0; i--) {
    const m = physical[i];
    const key = `${m.variant_id}|${m.warehouse_id}`;
    previousBalance.set(m.id, lastSeen.has(key) ? lastSeen.get(key) : null);
    lastSeen.set(key, m.balance_after);
  }

  return list.map((m) => {
    const availability = !isPhysical(m);
    let delta = null;
    if (availability) delta = 0;
    else if (m.direction === "in") delta = Number(m.quantity);
    else if (m.direction === "out") delta = -Number(m.quantity);
    else if (m.direction === "adjust") {
      const before = previousBalance.get(m.id);
      delta = before === null || before === undefined ? null : Number(m.balance_after) - Number(before);
    }
    return {
      id: m.id,
      variantId: m.variant_id,
      warehouseId: m.warehouse_id,
      date: m.created_at,
      reason: m.reason,
      label: reasonLabel(m.reason),
      availabilityOnly: availability,
      delta, // signed change of on_hand; 0 for a reservation row; null = not derivable from the window
      qtyIn: delta !== null && delta > 0 ? delta : 0,
      qtyOut: delta !== null && delta < 0 ? -delta : 0,
      isCount: m.direction === "adjust",
      counted: m.direction === "adjust" ? Number(m.quantity) : null,
      balance: availability ? null : Number(m.balance_after),
      docType: m.reference_type ?? null,
      docId: m.reference_id ?? null,
    };
  });
}

/** Query string for the ledger of one variant. */
export function movementsQuery({ variantId, reason, limit = 200 } = {}) {
  const q = new URLSearchParams();
  if (variantId) q.set("variant_id", variantId);
  if (reason && reason in REASON_LABEL) q.set("reason", reason);
  q.set("limit", String(Math.max(1, Math.min(Number(limit) || 200, 500))));
  return q.toString();
}

/**
 * Attach the product name, colour/size and SKU of each movement's variant. `variants` maps variant id to
 * a stock row (see stockRowFromApi). A variant that is no longer in the stock list (archived) keeps its
 * movement, labelled as unknown, instead of the row being dropped. Availability-only rows (a hold on
 * stock that did not move on_hand) are left out of the ledger screen: they are not stock movements.
 */
export function describeMovements(rows, variants) {
  return rows
    .filter((m) => !m.availabilityOnly)
    .map((m) => {
      const v = variants.get(m.variantId);
      return {
        ...m,
        productName: v?.productName ?? "منتج غير معروض",
        color: v?.color ?? "",
        size: v?.size ?? "",
        sku: v?.sku ?? "",
        doc: m.docId ? `${m.docType ?? ""} ${String(m.docId).slice(0, 8)}`.trim() : "—",
      };
    });
}

/** Ledger-wide totals for the stats strip. `docs` counts distinct source documents, not rows. */
export function movementTotals(rows) {
  return {
    in: rows.reduce((s, m) => s + (m.qtyIn || 0), 0),
    out: rows.reduce((s, m) => s + (m.qtyOut || 0), 0),
    docs: new Set(rows.filter((m) => m.docId).map((m) => m.docId)).size,
  };
}
