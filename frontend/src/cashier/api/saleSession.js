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
    cart.map((l) => [l.variantId, l.qty]),
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
        .then((receipt) => {
          intent = null; // success: the next sale is a new intent
          intentFor = null;
          return receipt;
        })
        .finally(() => {
          inflight = null;
          inflightFor = null;
        });
      return inflight;
    },
  };
}
