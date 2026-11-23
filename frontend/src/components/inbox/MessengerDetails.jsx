import React, { useState } from "react";
import { ChevronDown, Palette, Search, User, X } from "lucide-react";
import { cn } from "@/lib/utils";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import { messengerSharedItems } from "./messengerChat";

// Messenger's own details panel: the person, three round actions, and four folded sections.
// Only what the platform really has is shown: no mute, no members and no encryption claim, because
// the Page API offers none of them.
const SECTIONS = (isAr) => [
  { id: "info", label: isAr ? "معلومات الدردشة" : "Chat info" },
  { id: "customize", label: isAr ? "تخصيص الدردشة" : "Customize chat" },
  { id: "media", label: isAr ? "الوسائط والملفات والروابط" : "Media, files and links" },
];

function Action({ icon: Icon, label, onClick, testId }) {
  return (
    <button type="button" data-testid={testId} onClick={onClick} className="flex w-[72px] flex-col items-center gap-1.5 text-[12px] text-[#050505]">
      <span className="grid h-9 w-9 place-items-center rounded-full bg-[#e4e6eb]"><Icon className="h-[18px] w-[18px]" /></span>
      <span className="text-center leading-tight">{label}</span>
    </button>
  );
}

export default function MessengerDetails({ conversation, customerName, isAr, onClose, onOpenCustomerProfile, onSearch, onTheme }) {
  const [open, setOpen] = useState(null);
  const shared = messengerSharedItems(conversation?.messages);
  return (
    <div data-testid="messenger-details" className="flex min-h-0 flex-1 flex-col bg-white text-[#050505]">
      <div className="flex h-12 shrink-0 items-center justify-end px-3">
        <button type="button" onClick={onClose} aria-label={isAr ? "إغلاق" : "Close"} className="grid h-8 w-8 place-items-center rounded-full text-[#65676b] hover:bg-[#f0f2f5]"><X className="h-5 w-5" /></button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <div className="flex flex-col items-center gap-2 pb-4">
          <ConversationAvatar conversation={conversation} className="h-[72px] w-[72px] text-[22px]" />
          <h4 className="text-[17px] font-bold" dir="auto">{customerName}</h4>
        </div>
        <div className="flex justify-center gap-3 pb-4">
          <Action testId="messenger-action-profile" icon={User} label={isAr ? "ملف العميل" : "Profile"} onClick={() => { onClose(); onOpenCustomerProfile?.(conversation); }} />
          <Action testId="messenger-action-search" icon={Search} label={isAr ? "بحث" : "Search"} onClick={() => onSearch?.()} />
        </div>
        {SECTIONS(isAr).map((section) => (
          <div key={section.id}>
            <button type="button" data-testid={`messenger-section-${section.id}`} aria-expanded={open === section.id} onClick={() => setOpen(open === section.id ? null : section.id)} className="flex h-11 w-full items-center justify-between rounded-lg px-2 text-[15px] font-semibold hover:bg-[#f0f2f5]">
              <span>{section.label}</span>
              <ChevronDown className={cn("h-4 w-4 text-[#65676b] transition-transform", open === section.id && "rotate-180")} />
            </button>
            {open === section.id && (
              <div className="px-2 pb-2 text-[14px]">
                {section.id === "info" && <div className="text-[#65676b]">{isAr ? "قناة" : "Channel"}: Messenger</div>}
                {section.id === "customize" && (
                  <button type="button" data-testid="messenger-action-theme" onClick={() => onTheme?.()} className="flex h-10 w-full items-center gap-3 rounded-lg px-2 hover:bg-[#f0f2f5]">
                    <Palette className="h-5 w-5 text-[#0084ff]" /><span>{isAr ? "السمة" : "Theme"}</span>
                  </button>
                )}
                {section.id === "media" && (
                  shared.media.length + shared.files.length + shared.links.length === 0 ? (
                    <div data-testid="messenger-shared-empty" className="py-2 text-[#65676b]">{isAr ? "لا توجد وسائط أو ملفات أو روابط بعد" : "No media, files or links yet"}</div>
                  ) : (
                    <div className="space-y-3">
                      {shared.media.length > 0 && (
                        <div className="grid grid-cols-3 gap-1">
                          {shared.media.map((m) => <img key={m.id} src={m.mediaUrl} alt="" loading="lazy" className="aspect-square w-full rounded object-cover" />)}
                        </div>
                      )}
                      {shared.files.map((m) => <a key={m.id} href={m.mediaUrl} target="_blank" rel="noreferrer" className="block truncate text-[#0064d1]">{m.fileName || m.mediaUrl}</a>)}
                      {shared.links.map((l, i) => <a key={`${l.id}-${i}`} href={l.url} target="_blank" rel="noreferrer" className="block truncate text-[#0064d1]" dir="ltr">{l.url}</a>)}
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
