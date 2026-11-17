import React from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import WhatsAppBubble, { WHATSAPP_FONT } from "../src/components/inbox/whatsapp/WhatsAppBubble";
import { EmojiIcon, MicIcon, PlusIcon, SendIcon, WhatsAppChannelBadge } from "../src/components/inbox/whatsapp/icons";

const th = { out: "#d9fdd3", outText: "#111b21", in: "#ffffff", inText: "#111b21", tail: true };
const q = new URLSearchParams(location.search);
const mobile = q.get("m") === "1";
const msgs = [
  { id: 1, side: "in", text: "السلام عليكم، عايز أعرف سعر الطقم الأحمر", time: "٠٨:٣١ م", reactions: [] },
  { id: 2, side: "out", text: "وعليكم السلام، الطقم بـ ٣٥٠ جنيه وموجود مقاس M و L", time: "٠٨:٣٢ م", status: "read", reactions: ["👍"] },
  { id: 3, side: "in", text: "تمام، وعايز لون أسود كمان", time: "٠٨:٣٣ م", replyTo: { available: true, direction: "outbound", content_type: "text", body: "الطقم بـ ٣٥٠ جنيه وموجود مقاس M و L" }, reactions: [] },
  { id: 4, side: "out", text: "ثواني أراجع المخزن", time: "٠٨:٣٤ م", status: "delivered", edited: true, reactions: [] },
  { id: 5, side: "in", text: "x", time: "٠٨:٣٥ م", deleted: true, reactions: [] },
  { id: 6, side: "out", text: "اتأكدت، الأسود متاح", time: "٠٨:٣٦ م", status: "failed", reactions: [] },
  { id: 7, side: "out", text: "هبعتلك الصور حالاً", time: "٠٨:٣٧ م", status: "queued", reactions: [] },
  { id: 8, side: "in", text: "رد على رسالة قديمة", time: "٠٨:٣٨ م", replyTo: { id: null, available: false }, reactions: ["❤️", "😂"] },
];
function Bar() {
  const b = "grid h-10 w-10 place-items-center rounded-full text-[#54656f]";
  return (
    <div dir="ltr" style={{ background: "#f0f2f5", fontFamily: WHATSAPP_FONT }} className="flex min-h-[52px] items-center gap-1 px-1 py-1.5">
      <span className={b}><EmojiIcon size={26} /></span><span className={b}><PlusIcon size={26} /></span>
      <div className="mx-1 flex h-[42px] flex-1 items-center rounded-lg bg-white px-3 text-[15px] text-[#667781]" dir="auto">اكتب رسالة</div>
      <span className={b}><MicIcon size={24} /></span><span className={b}><SendIcon size={24} className="-scale-x-100" /></span>
    </div>
  );
}
createRoot(document.getElementById("root")).render(
  <div style={{ width: mobile ? 390 : 760, margin: "0 auto", fontFamily: WHATSAPP_FONT }}>
    <div style={{ background: "#fff", padding: 10, display: "flex", gap: 10, alignItems: "center", borderBottom: "1px solid #d1d7db" }}>
      <WhatsAppChannelBadge size={28} className="text-[#25d366]" /><b style={{ color: "#111b21" }}>سارة أحمد</b>
    </div>
    <div dir="rtl" style={{ background: "#efeae2", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
      {msgs.map((m) => <WhatsAppBubble key={m.id} m={m} th={th} lang="ar" />)}
    </div>
    <Bar />
  </div>,
);
