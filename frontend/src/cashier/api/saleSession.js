/**
 * One object per open shift that owns the "money" side of a sale.
 *
 * Retry safety: an Idempotency-Key is bound to the exact payment it was created for (cart +
 * discount + tenders). The same payment re-sent after a network failure reuses the key, so the
 * server replays the first answer instead of selling twice. A different payment (the cashier
 * changed the cart) gets a NEW key, otherwise the server would replay a receipt for another cart.
 * A second tap while a request is still in flight joins that request instead of sending another.
 */
import { newIntent, posApi } from "./posApi";
import { buildSellPayload, cartItems } from "./checkout";
import { fromMinor, toMinor } from "./money";

const fingerprint = ({ cart, discountTotal, customerId, tenders }) =>
  JSON.stringify([
    // the line's own discount is part of the payment: same item and quantity with another discount is another sale
    cart.map((l) => [l.variantId, l.qty, (Number(l.discountPct) || 0).toFixed(2)]),
    discountTotal ? fromMinor(toMinor(discountTotal)) : "",
    customerId ?? "",
    (tenders ?? []).map((t) => [t.method, fromMinor(toMinor(t.amount || 0))]),
  ]);

export function createSaleSession(sessionId) {
  let intent = null;
  let intentFor = null;
  let inflight = null;
  let inflightFor = null;

  return {
    async quote({ cart, discountTotal }) {
      if (!cart?.length) return { subtotal: "0.00", discountTotal: "0.00", total: "0.00" };
      const r = await posApi.quote(sessionId, { items: cartItems(cart), discountTotal });
      return { subtotal: r.subtotal, discountTotal: r.discount_total, total: r.grand_total };
    },

    /**
     * Sell AND fetch the receipt as ONE unit. The key is released only after both succeeded:
     * if the sale went through but the receipt read failed, the next tap on the same cart re-sends
     * the SAME key, the server replays the first sale, and we retry only the read. Releasing the
     * key right after /sell (as before) made that retry a second, separate sale.
     */
    async pay({ cart, total, discountTotal, customerId, tenders }) {
      const payload = buildSellPayload({ cart, total, discountTotal, customerId, tenders }); // throws if unpaid/empty
      const fp = fingerprint({ cart, discountTotal, customerId, tenders });
      if (inflight && inflightFor === fp) return inflight;

      if (!intent || intentFor !== fp) {
        intent = newIntent();
        intentFor = fp;
      }
      const sent = intent;
      inflightFor = fp;
      inflight = posApi
        .sell(sessionId, payload, sent)
        .then(async (sold) => {
          const detail = await posApi.receipt(sold.receipt_id);
          intent = null; // sale AND receipt are in hand: the next sale is a new intent
          intentFor = null;
          return { sold, detail };
        })
        .finally(() => {
          inflight = null;
          inflightFor = null;
        });
      return inflight;
    },
  };
}
