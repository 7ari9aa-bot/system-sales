import React, { useMemo, useState } from "react";
import IgAvatar from "./IgAvatar";
import { IgClose, IgSearch } from "./igIcons";
import { IG } from "./igTheme";
import { cn } from "@/lib/utils";

/** Instagram's "Share" sheet: pick a chat and the post goes into it as a card the customer can open. */
export default function IgSharePanel({ threads = [], lang = "ar", onSend, onClose }) {
  const isArabic = lang === "ar";
  const [query, setQuery] = useState("");
  const [sentTo, setSentTo] = useState({});
  const [failed, setFailed] = useState("");
  const [busy, setBusy] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Archived and request chats are not somewhere a shop shares into.
    return threads
      .filter((row) => !row.archivedAt && (row.folder || "primary") === "primary")
      .filter((row) => !q || String(row.customer || "").toLowerCase().includes(q))
      .slice(0, 50);
  }, [threads, query]);

  async function send(row) {
    setBusy(row.id);
    setFailed("");
    const ok = await onSend(row.id);
    setBusy("");
    if (ok) setSentTo((prev) => ({ ...prev, [row.id]: true }));
    else setFailed(isArabic ? "تعذّر الإرسال. حاول مرة أخرى." : "Couldn't send. Try again.");
  }

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/60 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <div role="dialog" aria-modal="true" aria-label={isArabic ? "مشاركة" : "Share"} data-testid="ig-share-panel"
        className="flex max-h-[min(560px,90vh)] w-full max-w-[400px] flex-col overflow-hidden rounded-xl bg-white text-[#0c1014]">
        <div className="relative flex h-[43px] shrink-0 items-center justify-center border-b" style={{ borderColor: IG.separator }}>
          <h2 className="text-[16px] font-semibold">{isArabic ? "مشاركة" : "Share"}</h2>
          <button type="button" onClick={onClose} aria-label={isArabic ? "إغلاق" : "Close"} className="absolute end-3 hover:opacity-60"><IgClose /></button>
        </div>
        <label className="m-3 flex h-10 shrink-0 items-center gap-2 rounded-full px-4" style={{ background: IG.hover }}>
          <IgSearch size={16} className="text-[#6a717a]" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? "بحث" : "Search"} aria-label={isArabic ? "بحث" : "Search"}
            className="h-full min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-[#6a717a]" />
        </label>
        <ul className="min-h-0 flex-1 overflow-y-auto pb-2">
          {rows.length === 0 && <li className="px-6 py-8 text-center text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "لا توجد محادثات." : "No chats."}</li>}
          {rows.map((row) => (
            <li key={row.id} className="flex items-center gap-3 px-4 py-2">
              <IgAvatar src={row.avatarUrl} size={44} />
              <span dir="auto" className="min-w-0 flex-1 truncate text-[14px]">{row.customer}</span>
              <button type="button" data-testid="ig-share-send" disabled={busy === row.id || sentTo[row.id]} onClick={() => send(row)}
                className={cn("rounded-lg px-4 py-[7px] text-[14px] font-semibold disabled:opacity-60", sentTo[row.id] ? "bg-[#f0f2f5]" : "text-white")}
                style={sentTo[row.id] ? undefined : { background: IG.blue }}>
                {sentTo[row.id] ? (isArabic ? "تم الإرسال" : "Sent") : (isArabic ? "إرسال" : "Send")}
              </button>
            </li>
          ))}
        </ul>
        {failed && <p role="alert" className="shrink-0 border-t px-4 py-2 text-[12px] text-[#ed4956]" style={{ borderColor: IG.separator }}>{failed}</p>}
      </div>
    </div>
  );
}
