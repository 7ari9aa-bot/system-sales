/**
 * A counter return, planned in the browser and settled by the backend.
 * The backend decides the truth (caps, prices, which tender the money goes back to); this file
 * only builds the request and an ESTIMATE of the refund that follows the backend's own formula:
 *   net(line)    = gross(line) - round_half_up(gross(line) * line_pct / 100)       (what the customer paid)
 *   refund(line) = net(line) - round_half_up(order_level_discount * net(line) / sold_net_subtotal)
 * where order_level_discount is what is left of the order discount after every line discount.
 * Money is integer cents throughout. After the call, the server's refunded_total is what we show.
 */
import { fromMinor, toMinor } from "./money";

/** Lines of a sale receipt that can still come back: sold - returned. */
export function returnableLines(saleDetail) {
  return (saleDetail.lines ?? []).map((l) => {
    const sold = Number(l.quantity);
    const returned = Number(l.returned_qty ?? 0);
    return {
      variantId: l.variant_id,
      name: l.title ?? l.sku ?? "—",
      sku: l.sku ?? "",
      unitPriceMinor: toMinor(l.unit_price),
      linePct: Number(l.discount_pct ?? 0) || 0,
      sold,
      alreadyReturned: returned,
      maxQty: Math.max(0, sold - returned),
      returnQty: 0,
    };
  });
}

/** Gross of a sold line, in cents: what the lines sum to before ANY discount. */
export function orderSubtotalMinor(saleDetail) {
  return (saleDetail.lines ?? []).reduce((s, l) => s + toMinor(l.unit_price) * Number(l.quantity), 0);
}

function roundHalfUpDiv(numer, denom) {
  return Math.floor((2 * numer + denom) / (2 * denom));
}

/** A line's own discount in cents: gross * pct / 100, rounded half up (pct has at most 2 decimals). */
function lineDiscountMinor(grossMinor, pct) {
  const pctHundredths = Math.round((Number(pct) || 0) * 100); // 50.00 -> 5000
  return pctHundredths > 0 ? roundHalfUpDiv(grossMinor * pctHundredths, 10000) : 0;
}

/** What one sold line was actually charged, in cents (gross minus its own discount). */
function soldNetMinor(l) {
  const gross = toMinor(l.unit_price) * Number(l.quantity);
  return gross - lineDiscountMinor(gross, l.discount_pct);
}

/**
 * Estimated refund for the chosen lines, in cents, mirroring the backend's `_return_line_totals`:
 * the line's own discount comes off first; only the order-level discount (the part of the order
 * discount beyond all the line discounts) is shared out, in proportion to the NET of the lines.
 */
export function estimateRefundMinor(saleDetail, lines) {
  const sold = saleDetail.lines ?? [];
  const gross = orderSubtotalMinor(saleDetail);
  const netBase = sold.reduce((s, l) => s + soldNetMinor(l), 0);
  const orderDiscount = toMinor(saleDetail.order?.discount_total ?? "0");
  const orderLevel = Math.max(orderDiscount - (gross - netBase), 0);
  return lines
    .filter((l) => l.returnQty > 0)
    .reduce((sum, l) => {
      const lineGross = l.unitPriceMinor * l.returnQty;
      const net = lineGross - lineDiscountMinor(lineGross, l.linePct);
      const share = netBase > 0 && orderLevel > 0 ? roundHalfUpDiv(orderLevel * net, netBase) : 0;
      return sum + (net - share);
    }, 0);
}

export const estimateRefund = (saleDetail, lines) => fromMinor(estimateRefundMinor(saleDetail, lines));

export function setQty(lines, variantId, qty) {
  return lines.map((l) =>
    l.variantId === variantId ? { ...l, returnQty: Math.min(l.maxQty, Math.max(0, Math.trunc(Number(qty)) || 0)) } : l,
  );
}

export function returnRequest(saleDetail, lines, { restock }) {
  const picked = lines.filter((l) => l.returnQty > 0);
  if (!picked.length) throw new Error("اختر صنفًا واحدًا على الأقل للاسترجاع");
  return {
    orderId: saleDetail.order.id,
    lines: picked.map((l) => ({ variant_id: l.variantId, quantity: l.returnQty })),
    restock: Boolean(restock),
  };
}

/** A plain-language reason for the backend's refusals; anything unknown is passed through, never hidden. */
export function returnErrorMessage(err) {
  const m = String(err?.message ?? err ?? "");
  if (/different session/i.test(m)) return "هذه الفاتورة بيعت في وردية أخرى. المرتجع يتم على الوردية المفتوحة نفسها التي تم فيها البيع.";
  if (/session is closed/i.test(m)) return "الوردية مغلقة. افتح الوردية أولًا لتسجيل المرتجع.";
  if (/already returned/i.test(m)) return "تم استرجاع هذه الكمية من قبل. حدّث الفاتورة وراجع المتاح.";
  if (/still out of the shelf/i.test(m)) return "الكمية المطلوب إرجاعها للرف أكبر من الخارج منها فعلًا. جرّب بدون إرجاع للمخزون.";
  if (/refund methods .* not enabled/i.test(m)) return "طريقة الدفع الأصلية للفاتورة غير مسموح بالاسترداد عليها في هذا البروفايل.";
  return m || "تعذّر تنفيذ المرتجع";
}

/** The shape the return tables render (they predate the backend: barcode/size/colour are optional there). */
export function tableLine(l) {
  return {
    ...l,
    key: l.variantId,
    barcode: l.sku,
    code: l.sku,
    size: "",
    color: "",
    qty: l.sold,
    unitNet: Number(fromMinor(l.unitPriceMinor)),
    total: Number(fromMinor(l.unitPriceMinor * l.sold)),
  };
}

/**
 * Send the return; if the backend says the SAME intent is still being processed (409 "in progress"),
 * wait and re-send the same intent: the backend then replays the first answer, so nothing is refunded twice.
 */
export async function sendReturn(send, { tries = 4, waitMs = 1200, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let last;
  for (let i = 0; i < tries; i += 1) {
    try {
      return await send();
    } catch (e) {
      last = e;
      if (!/in progress/i.test(String(e?.message ?? e))) throw e;
      await sleep(waitMs);
    }
  }
  throw last;
}
