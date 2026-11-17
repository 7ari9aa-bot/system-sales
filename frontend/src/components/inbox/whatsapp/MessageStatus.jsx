import React from "react";
import { AlertIcon, ClockIcon, DoubleTickIcon, TickIcon } from "./icons";

// What the sender sees at the end of an outgoing bubble:
//   queued     clock         not handed to WhatsApp yet
//   sent       one grey tick accepted by WhatsApp
//   delivered  two grey ticks reached the phone
//   read       two blue ticks opened
//   failed     red alert      never delivered, and the merchant must know
// Anything unrecognised falls back to the clock, never to a tick: showing a
// delivered mark for a message we cannot vouch for is the one wrong answer.
export function statusKind(status) {
  switch (String(status || "").toLowerCase()) {
    case "read":
      return "read";
    case "delivered":
      return "delivered";
    case "sent":
      return "sent";
    case "failed":
      return "failed";
    default:
      return "queued";
  }
}

const LABEL = {
  ar: { queued: "قيد الإرسال", sent: "تم الإرسال", delivered: "تم التسليم", read: "تمت القراءة", failed: "فشل الإرسال" },
  en: { queued: "Sending", sent: "Sent", delivered: "Delivered", read: "Read", failed: "Failed to send" },
};

export default function MessageStatus({ status, lang = "ar", className = "" }) {
  const kind = statusKind(status);
  const label = (LABEL[lang] || LABEL.en)[kind];
  const common = { role: "img", "aria-label": label, title: label, "data-status": kind, className };
  if (kind === "read") return <span {...common}><DoubleTickIcon size={17} className="text-[#53bdeb]" /></span>;
  if (kind === "delivered") return <span {...common}><DoubleTickIcon size={17} className="text-[#667781]" /></span>;
  if (kind === "sent") return <span {...common}><TickIcon size={14} className="text-[#667781]" /></span>;
  if (kind === "failed") return <span {...common}><AlertIcon size={15} className="text-[#ea0038]" /></span>;
  return <span {...common}><ClockIcon size={13} className="text-[#667781]" /></span>;
}
