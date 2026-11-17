// WhatsApp lets a business reply freely for 24 hours after the customer's LAST
// message. After that only an approved template may be sent. This mirrors the
// server's rule (channel policy "whatsapp": 24h, anchored on the last INBOUND
// message, never on our own replies) so the header can say it before the
// agent types a reply that the server will refuse.

export const WINDOW_HOURS = 24;
const HOUR = 3600 * 1000;

/**
 * @returns {{ state: "open"|"closing"|"closed"|"never", expiresAt: Date|null, msLeft: number }}
 *  open    more than 2h left        closing  2h or less left
 *  closed  24h passed               never    the customer has never written
 */
export function replyWindow(lastCustomerMessageAt, now = new Date()) {
  if (!lastCustomerMessageAt) return { state: "never", expiresAt: null, msLeft: 0 };
  const anchor = new Date(lastCustomerMessageAt);
  if (Number.isNaN(anchor.getTime())) return { state: "never", expiresAt: null, msLeft: 0 };
  const expiresAt = new Date(anchor.getTime() + WINDOW_HOURS * HOUR);
  const msLeft = expiresAt.getTime() - new Date(now).getTime();
  if (msLeft <= 0) return { state: "closed", expiresAt, msLeft: 0 };
  return { state: msLeft <= 2 * HOUR ? "closing" : "open", expiresAt, msLeft };
}

/** "5h 20m", "45m", "under a minute" (or Arabic), for the time still left. */
export function formatLeft(msLeft, lang = "en") {
  const totalMin = Math.floor(Math.max(0, msLeft) / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const ar = lang === "ar";
  if (totalMin < 1) return ar ? "أقل من دقيقة" : "under a minute";
  if (h === 0) return ar ? `${m} د` : `${m}m`;
  if (m === 0) return ar ? `${h} س` : `${h}h`;
  return ar ? `${h} س ${m} د` : `${h}h ${m}m`;
}

/** The one line the header shows under the name. */
export function headerSubtitle({ phone, windowInfo, lang = "en" }) {
  const ar = lang === "ar";
  const parts = [];
  if (phone) parts.push(phone);
  if (windowInfo.state === "closed") parts.push(ar ? "انتهت نافذة الرد" : "Reply window closed");
  else if (windowInfo.state === "closing") parts.push(ar ? `تنتهي نافذة الرد بعد ${formatLeft(windowInfo.msLeft, lang)}` : `Reply window ends in ${formatLeft(windowInfo.msLeft, lang)}`);
  return parts.join(" · ");
}
