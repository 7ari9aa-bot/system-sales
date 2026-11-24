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
      restock: null, // null = follow the whole return's choice; true/false = this piece's own
      // What state the piece comes back in. The server decides what each one does to stock.
      condition: "sellable",
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

/**
 * The five conditions a returned piece can come back in, and what each does to stock. The server
 * owns the effect (``PosService._restock_returned``); these labels only tell the cashier the truth
 * before the piece is accepted, so a torn shirt is never silently put back on the rail.
 */
export const CONDITIONS = [
  { value: "sellable", label: "صالحة للبيع", effect: "ترجع للرف وتتاح للبيع" },
  { value: "quarantine", label: "تحت الفحص", effect: "تتحسب في المخزن لكن مش متاحة للبيع" },
  { value: "damaged", label: "تالفة", effect: "تتحسب في المخزن ومعزولة، مش متاحة للبيع" },
  { value: "writeoff", label: "شطب", effect: "مش ترجع للمخزون خالص" },
  { value: "supplier", label: "ترجع للمورد", effect: "مش ترجع للمخزون" },
];

export const conditionLabel = (value) => CONDITIONS.find((c) => c.value === value)?.label ?? value;

/** A condition's effect in one line of Arabic, or "" for an unknown value. */
export const conditionEffect = (value) => CONDITIONS.find((c) => c.value === value)?.effect ?? "";

/** Whether a condition puts the piece back on the shelf as sellable stock. */
export const isSellable = (value) => (value ?? "sellable") === "sellable";

/** This piece's own condition (a jacket sellable, a torn shirt damaged). Unknown values are kept as given. */
export function setLineCondition(lines, variantId, condition) {
  return lines.map((l) => (l.variantId === variantId ? { ...l, condition: String(condition) } : l));
}

/** How the picked pieces split across conditions, in the order of CONDITIONS, for the summary line. */
export function conditionSplit(lines) {
  return CONDITIONS.map((c) => ({
    ...c,
    units: lines.filter((l) => l.returnQty > 0 && (l.condition ?? "sellable") === c.value).reduce((n, l) => n + l.returnQty, 0),
  })).filter((c) => c.units > 0);
}

/** This piece's own shelf decision (a jacket back on the rail, a torn shirt not). null clears it. */
export function setLineRestock(lines, variantId, restock) {
  return lines.map((l) => (l.variantId === variantId ? { ...l, restock: restock === null ? null : Boolean(restock) } : l));
}

/** What a line shows in its shelf box: its own choice, else the whole return's. */
export const lineRestock = (line, wholeRestock) => (line.restock === null || line.restock === undefined ? Boolean(wholeRestock) : line.restock);

/** The wire shape of one picked line: quantity, the reason, and a shelf choice only when the piece has its own. */
export function wireLine(l, reason) {
  return {
    variant_id: l.variantId,
    quantity: l.returnQty,
    ...(reason ? { reason } : {}),
    ...(l.restock === null || l.restock === undefined ? {} : { restock: Boolean(l.restock) }),
    // Always sent: the backend defaults to sellable, and a torn piece must never fall into that
    // default because the screen forgot to say what it was.
    condition: l.condition ?? "sellable",
  };
}

export function setQty(lines, variantId, qty) {
  return lines.map((l) =>
    l.variantId === variantId ? { ...l, returnQty: Math.min(l.maxQty, Math.max(0, Math.trunc(Number(qty)) || 0)) } : l,
  );
}

export function returnRequest(saleDetail, lines, { restock, reason } = {}) {
  const picked = lines.filter((l) => l.returnQty > 0);
  if (!picked.length) throw new Error("اختر صنفًا واحدًا على الأقل للاسترجاع");
  return {
    orderId: saleDetail.order.id,
    lines: picked.map((l) => wireLine(l, reason)),
    // Only sent once the cashier has a value; otherwise the shop's own default applies on the server.
    ...(restock === undefined || restock === null ? {} : { restock: Boolean(restock) }),
  };
}

const METHOD_LABEL = { cash: "نقدي", card: "بطاقة", transfer: "تحويل", wallet: "محفظة" };

/**
 * What the server says it did with the money on a return, in the shop's words. The screen prints
 * THIS, never the estimate it computed itself: only the server knows which tenders the original
 * sale collected, how much of each was already refunded, and what it could not give back.
 */
export function returnSettlementSummary(result) {
  const refunded = Number(result?.refunded ?? 0);
  // A card reversal is promised at the counter and proven at the machine. Saying "اترد" about it
  // before the cashier confirms the reference tells the customer they were paid back when they
  // were not, so the pending part is named separately.
  const pending = (result?.awaiting_confirmation ?? []).reduce(
    (sum, row) => sum + Number(row.amount ?? 0),
    0,
  );
  const manual = (result?.terminal_only ?? []).reduce(
    (sum, row) => sum + Number(row.amount ?? 0),
    0,
  );
  const withPending = (text) =>
    pending > 0
      ? `${text} — منها ${pending.toFixed(2)} ج.م على البطاقة/المحفظة لسه مستنية تأكيد الماكينة`
      : text;
  const withManual = (text) =>
    manual > 0
      ? `${text} — ${manual.toFixed(2)} ج.م يترد يدويًا على الماكينة ويُسجَّل رقم المرجع`
      : text;
  const uncollected = Number(result?.refund_uncollected ?? 0);
  const byMethod = result?.refund_by_method ?? {};
  const parts = [];
  if (result?.refund_mode === "record_only") {
    parts.push("الكاشير مش بيسجّل مدفوعات، فالمبلغ مسجّل على الفاتورة فقط");
  } else if (result?.refund_mode === "nothing_collected") {
    parts.push("الفاتورة الأصلية ما حصّلتش المبلغ ده، فمفيش مبلغ يترد");
  } else {
    // ``refunded`` from the server is already the money that actually went back; the pending card
    // slice is reported separately below, so subtracting it here counted it twice and showed zero.
    const confirmed = refunded;
    parts.push(withPending(withManual(`اترد ${confirmed.toFixed(2)} ج.م`)));
  }
  const methods = Object.entries(byMethod)
    .map(([method, value]) => `${METHOD_LABEL[method] ?? method} ${value}`)
    .join(" · ");
  if (methods) parts.push(methods);
  if (uncollected > 0) parts.push(`منها ${uncollected.toFixed(2)} ج.م لم تُحصَّل أصلًا فلم تُرَد`);
  if (byMethod.cash) parts.push("النقدي خرج من درج الوردية");
  return parts.join(" — ");
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

/** One sold line's charged total in cents from a returnable line (gross minus its own discount). */
function soldNetMinorOf(l) {
  const gross = l.unitPriceMinor * l.sold;
  return gross - lineDiscountMinor(gross, l.linePct);
}

/** One piece's charged price in cents, rounded half up like the backend's per-line figure. */
function unitNetMinor(l) {
  return l.sold > 0 ? roundHalfUpDiv(soldNetMinorOf(l), l.sold) : l.unitPriceMinor;
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
    // What the customer really paid: the line's own discount comes off, so a 300 shirt sold at 10% off
    // reads 270 here, the same figure the refund estimate and the server use.
    unitNet: Number(fromMinor(unitNetMinor(l))),
    total: Number(fromMinor(soldNetMinorOf(l))),
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
