/**
 * One object per open day that records a sale (it never takes or handles money).
 *
 * Retry safety: an Idempotency-Key is bound to the exact sale it was created for (cart +
 * discount + customer + note). The same sale re-sent after a network failure reuses the key, so the
 * server replays the first answer instead of selling twice. A different payment (the cashier
 * changed the cart) gets a NEW key, otherwise the server would replay a receipt for another cart.
 * A second tap while a request is still in flight joins that request instead of sending another.
 */
import { newIntent, posApi } from "./posApi";
import { cartItems } from "./checkout";
import { fromMinor, toMinor } from "./money";

const saleFingerprint = ({ cart, discountTotal, customerId, customerPhone, customerName, note, payments, onAccount }) =>
  JSON.stringify([
    cart.map((l) => [l.variantId, l.qty, (Number(l.discountPct) || 0).toFixed(2)]),
    discountTotal ? fromMinor(toMinor(discountTotal)) : "",
    customerId ?? "",
    // another phone is another customer on the invoice: a retry must replay the SAME sale
    String(customerPhone ?? "").trim(),
    String(customerName ?? "").trim(),
    // another remark is another invoice: a retry must replay the SAME sale, never a different one
    String(note ?? "").trim(),
    // another way of paying (or putting the rest on the account) is another sale: the server
    // replays the FIRST answer under a key, so a changed tender under an old key would be lost
    (payments ?? []).map((p) => [p.method, p.amount, p.tendered ?? "", String(p.reference ?? "").trim()]),
    onAccount ? 1 : 0,
  ]);

/** The body `recordSale` takes. ONE builder for the online tap and the offline queue, so they cannot drift apart. */
const salePayload = ({ cart, discountTotal, customerId, customerPhone, customerName, note, payments, onAccount }) => ({
  items: cartItems(cart),
  customerId: customerId || undefined,
  customerPhone: customerId ? undefined : customerPhone,
  customerName: customerId ? undefined : customerName,
  discountTotal: discountTotal || undefined,
  note,
  // only a till that records payments sends these (see tenderPlan.js)
  payments: payments?.length ? payments : undefined,
  onAccount: onAccount || undefined,
});

export function createSaleSession(sessionId, registerId) {
  let intent = null;
  let intentFor = null;
  let inflight = null;
  let inflightFor = null;

  return {
    /**
     * The sale as the offline queue must keep it: the exact body `recordSale` takes, plus the key to
     * replay it under. If this very sale was already sent (the reply may have been lost on a weak
     * connection) the key is THAT sale's key, so the server hands back the first answer instead of
     * booking it twice; otherwise a fresh key is minted and kept for the same cart.
     */
    offlineSnapshot(sale) {
      const fp = saleFingerprint(sale);
      if (!intent || intentFor !== fp) {
        intent = newIntent();
        intentFor = fp;
      }
      return { payload: salePayload(sale), intentKey: intent.key };
    },

    async quote({ cart, discountTotal }) {
      if (!cart?.length) return { subtotal: "0.00", discountTotal: "0.00", total: "0.00" };
      const r = await posApi.quote(sessionId, { items: cartItems(cart), discountTotal });
      return { subtotal: r.subtotal, discountTotal: r.discount_total, total: r.grand_total };
    },

    /**
     * Record the sale and read its receipt as ONE unit: no tender, no change, no payment method.
     * Same retry rule as `pay`: the key lives until sale AND receipt are in hand, a changed cart
     * (or a changed line discount) is a new sale, and a second tap joins the request in flight.
     */
    async confirm({ cart, discountTotal, customerId, customerPhone, customerName, note, payments, onAccount }) {
      if (!cart?.length) throw new RangeError("checkout: the cart is empty");
      const fp = saleFingerprint({ cart, discountTotal, customerId, customerPhone, customerName, note, payments, onAccount });
      if (inflight && inflightFor === fp) return inflight;
      if (!intent || intentFor !== fp) {
        intent = newIntent();
        intentFor = fp;
      }
      const sent = intent;
      inflightFor = fp;
      inflight = posApi
        .recordSale(registerId, salePayload({ cart, discountTotal, customerId, customerPhone, customerName, note, payments, onAccount }), sent)
        .then(async (sold) => {
          const detail = await posApi.receipt(sold.receipt_id);
          intent = null;
          intentFor = null;
          // "phone_not_recorded": the sale went through but the typed phone could not be attached.
          return { sold, detail, customerNotice: sold.customer_notice ?? null };
        })
        .finally(() => {
          inflight = null;
          inflightFor = null;
        });
      return inflight;
    }
  };
}
