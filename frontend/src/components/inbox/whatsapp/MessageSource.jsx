/**
 * Who actually sent an OUTBOUND message.
 *
 * On a coexistence number the same thread is written from three places: the AI in FIHRIST, a
 * person in FIHRIST, and the merchant's own phone (the WhatsApp Business app). The backend stamps
 * every imported message with its origin, so the bubble can say which one it was instead of
 * drawing a reply typed on the phone as if the AI had written it — the exact confusion a
 * coexistence launch cannot afford.
 */
export const SOURCE_BUSINESS_APP = "whatsapp_business_app";
export const SOURCE_HISTORY = "whatsapp_history";

const LABELS = {
  ar: { business_app: "تطبيق واتساب", ai: "AI", fihrist: "فهرست" },
  en: { business_app: "Business App", ai: "AI", fihrist: "FIHRIST" },
};

/**
 * The label a bubble shows, or null when there is nothing honest to add.
 *
 * Inbound messages carry no label: the customer is the only sender on that side. A deleted
 * message shows its tombstone instead.
 */
export function messageSourceLabel(m, lang = "en") {
  if (!m || m.deleted) return null;
  if (m.side !== "out") return null;
  const words = LABELS[lang] || LABELS.en;
  if (m.source === SOURCE_BUSINESS_APP || m.source === SOURCE_HISTORY) {
    // History was written on the phone too, so it gets the same name.
    return { key: "business_app", text: words.business_app };
  }
  if (m.ai || m.senderType === "ai") return { key: "ai", text: words.ai };
  if (m.senderType === "agent") return { key: "fihrist", text: words.fihrist };
  return null;
}

export default function MessageSource({ m, lang = "en", className = "" }) {
  const label = messageSourceLabel(m, lang);
  if (!label) return null;
  return (
    <span
      data-testid="message-source"
      data-source={label.key}
      dir="auto"
      className={`whitespace-nowrap ${className}`}
    >
      {label.text}
    </span>
  );
}
