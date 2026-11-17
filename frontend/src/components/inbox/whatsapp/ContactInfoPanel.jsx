import React, { useEffect, useRef, useState } from "react";
import { ArchiveIcon, CloseIcon, FileIcon, MuteIcon, PushPinIcon, UnreadIcon } from "./icons";
import { countsOf, displayPhone, docsOf, mediaOf, sharedLinksOf } from "./contactInfo";
import { isMuted } from "./chatListState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: {
    title: "معلومات جهة الاتصال", close: "إغلاق", media: "الوسائط", docs: "المستندات", links: "الروابط",
    mediaLinksDocs: "الوسائط والروابط والمستندات", none: "لا يوجد شيء مشترك بعد",
    noMedia: "لا توجد وسائط مشتركة", noDocs: "لا توجد مستندات", noLinks: "لا توجد روابط",
    chatSettings: "إعدادات المحادثة", mute: "كتم الإشعارات", unmute: "إلغاء كتم الإشعارات", mutedForever: "مكتومة دائمًا",
    pin: "تثبيت المحادثة", unpin: "إلغاء التثبيت", archive: "أرشفة المحادثة", unarchive: "إلغاء الأرشفة",
    markUnread: "تعليم كغير مقروءة", sharedNote: "هذه الإعدادات مشتركة بين كل موظفي المتجر ولا تظهر للعميل.",
    store: "سجل العميل في المتجر", spent: "إجمالي المشتريات", openProfile: "عرض ملف العميل", lastSeen: "آخر نشاط",
    noBuy: "ممنوع من الشراء", noBuyHint: "لا يستطيع إتمام عمليات شراء. لا يؤثر على الرسائل.", allowBuy: "السماح بالشراء", blockBuy: "منع من الشراء",
    "8h": "8 ساعات", "1w": "أسبوع", always: "دائمًا", muteFor: "كتم لمدة",
    email: "البريد الإلكتروني", phone: "رقم الهاتف", open: "فتح",
  },
  en: {
    title: "Contact info", close: "Close", media: "Media", docs: "Docs", links: "Links",
    mediaLinksDocs: "Media, links and docs", none: "Nothing shared yet",
    noMedia: "No shared media", noDocs: "No documents", noLinks: "No links",
    chatSettings: "Chat settings", mute: "Mute notifications", unmute: "Unmute notifications", mutedForever: "Muted always",
    pin: "Pin chat", unpin: "Unpin chat", archive: "Archive chat", unarchive: "Unarchive chat",
    markUnread: "Mark as unread", sharedNote: "These settings are shared by everyone on your team and are never shown to the customer.",
    store: "Store customer record", spent: "Lifetime spend", openProfile: "Open customer profile", lastSeen: "Last active",
    noBuy: "Blocked from buying", noBuyHint: "Cannot complete purchases. Messages are not affected.", allowBuy: "Allow purchases", blockBuy: "Block purchases",
    "8h": "8 hours", "1w": "1 week", always: "Always", muteFor: "Mute for",
    email: "Email", phone: "Phone", open: "Open",
  },
};

function Section({ children, className }) {
  return <section className={cn("bg-white px-5 py-4 shadow-[0_1px_0_rgba(11,20,26,0.06)]", className)}>{children}</section>;
}

function Row({ icon: Icon, label, hint, onClick, testId, danger, disabled }) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className={cn("flex w-full items-center gap-5 py-2.5 text-start text-[15px] hover:bg-[#f5f6f6] focus-visible:bg-[#f5f6f6] focus-visible:outline-none disabled:opacity-50", danger ? "text-[#ea0038]" : "text-[#111b21]")}
    >
      <Icon size={20} className={danger ? "text-[#ea0038]" : "text-[#54656f]"} />
      <span className="min-w-0 flex-1">
        <span className="block">{label}</span>
        {hint && <span className="block text-[12.5px] text-[#667781]">{hint}</span>}
      </span>
    </button>
  );
}

/**
 * The WhatsApp "Contact info" panel. It shows only what the system knows: the
 * customer's real name and number, what was actually shared in this chat, the
 * shared chat settings, and the store's customer record. It claims nothing
 * about WhatsApp features this inbox does not have (encryption status,
 * disappearing messages, "About", starred messages).
 */
export default function ContactInfoPanel({ conversation, lang = "ar", customer = null, onClose, onChange, onToggleBuyBlock, onOpenCustomerProfile, onOpenImage, formatMoney }) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const [tab, setTab] = useState("media");
  const [muteOpen, setMuteOpen] = useState(false);

  useEffect(() => {
    ref.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!conversation) return null;
  const messages = conversation.messages || [];
  const counts = countsOf(messages);
  const total = counts.media + counts.docs + counts.links;
  const media = mediaOf(messages);
  const docs = docsOf(messages);
  const links = sharedLinksOf(messages);
  const phone = displayPhone(conversation.phone || customer?.phone);
  const email = customer?.email || "";
  const muted = isMuted(conversation);
  const pinned = Boolean(conversation.pinnedAt);
  const archived = Boolean(conversation.archivedAt);
  const blocked = Boolean(customer?.is_blocked);
  const set = (body) => () => onChange?.(body);

  return (
    <aside
      ref={ref}
      tabIndex={-1}
      role="complementary"
      aria-label={w.title}
      data-testid="contact-info"
      dir={lang === "ar" ? "rtl" : "ltr"}
      className="absolute inset-y-0 end-0 z-40 flex w-full flex-col overflow-hidden bg-[#f0f2f5] shadow-2xl outline-none sm:w-[380px]"
    >
      <header className="flex h-[60px] shrink-0 items-center gap-5 bg-[#f0f2f5] px-4 text-[#111b21]">
        <button type="button" onClick={onClose} aria-label={w.close} data-testid="contact-close" className="grid h-9 w-9 place-items-center rounded-full text-[#54656f] hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
          <CloseIcon size={20} />
        </button>
        <h3 className="text-[16px] font-medium">{w.title}</h3>
      </header>

      <div className="flex-1 space-y-2 overflow-y-auto scrollbar-thin pb-4">
        <Section className="flex flex-col items-center gap-1 py-6">
          <div className="grid h-[200px] w-[200px] max-w-full place-items-center rounded-full text-[56px] font-semibold text-[#54656f]" style={{ background: conversation.color || "#dfe5e7" }} aria-hidden="true">
            {conversation.initials}
          </div>
          <h4 dir="auto" data-testid="contact-name" className="mt-3 text-[22px] text-[#111b21]">{conversation.customer}</h4>
          {phone && <div dir="ltr" data-testid="contact-phone" className="text-[16px] text-[#667781]">{phone}</div>}
          {email && <div dir="ltr" className="text-[14px] text-[#667781]">{email}</div>}
        </Section>

        <Section className="pb-2">
          <div className="flex w-full items-center justify-between py-1 text-[14px] text-[#667781]">
            <span>{w.mediaLinksDocs}</span>
            <span className="tabular-nums">{total}</span>
          </div>
          <div role="tablist" className="mt-1 flex gap-4 border-b border-[#e9edef]">
            {["media", "docs", "links"].map((id) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} data-testid={`info-tab-${id}`} onClick={() => setTab(id)}
                className={cn("-mb-px border-b-2 pb-2 pt-1 text-[13.5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]", tab === id ? "border-[#00a884] font-medium text-[#008069]" : "border-transparent text-[#667781]")}>
                {w[id]} <span className="tabular-nums">{counts[id]}</span>
              </button>
            ))}
          </div>
          <div className="py-3" data-testid="info-body">
            {tab === "media" && (media.length ? (
              <div className="grid grid-cols-3 gap-1">
                {media.slice(0, 30).map((item) => (
                  <button key={item.id} type="button" data-testid="info-media" onClick={() => onOpenImage?.(item.id)} className="aspect-square overflow-hidden rounded bg-[#e9edef] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
                    {item.kind === "video" ? <video src={item.url} className="h-full w-full object-cover" muted preload="metadata" /> : <img src={item.url} alt="" loading="lazy" className="h-full w-full object-cover" />}
                  </button>
                ))}
              </div>
            ) : <p className="py-3 text-center text-[13px] text-[#667781]">{w.noMedia}</p>)}
            {tab === "docs" && (docs.length ? (
              <ul>{docs.map((d) => (
                <li key={d.id}><a href={d.url} target="_blank" rel="noopener noreferrer" data-testid="info-doc" className="flex items-center gap-3 py-2 text-[14px] text-[#111b21] hover:bg-[#f5f6f6]"><FileIcon size={20} className="text-[#54656f]" /><span dir="auto" className="truncate">{d.name || w.docs}</span></a></li>
              ))}</ul>
            ) : <p className="py-3 text-center text-[13px] text-[#667781]">{w.noDocs}</p>)}
            {tab === "links" && (links.length ? (
              <ul>{links.map((l) => (
                <li key={l.id}><a href={l.url} target="_blank" rel="noopener noreferrer" data-testid="info-link" className="block py-2 hover:bg-[#f5f6f6]"><span dir="ltr" className="block truncate text-[14px] text-[#027eb5]">{l.url}</span><span dir="ltr" className="block text-[12.5px] text-[#667781]">{l.host}</span></a></li>
              ))}</ul>
            ) : <p className="py-3 text-center text-[13px] text-[#667781]">{w.noLinks}</p>)}
          </div>
        </Section>

        <Section className="py-2">
          <p className="pb-1 pt-2 text-[13px] text-[#667781]">{w.chatSettings}</p>
          {muteOpen ? (
            <div role="group" aria-label={w.muteFor}>
              <p className="px-1 py-1 text-[13px] text-[#667781]">{w.muteFor}</p>
              {["8h", "1w", "always"].map((d) => (
                <button key={d} type="button" data-testid={`info-mute-${d}`} onClick={() => { onChange?.({ mute: d }); setMuteOpen(false); }} className="block w-full py-2.5 text-start text-[15px] hover:bg-[#f5f6f6]">{w[d]}</button>
              ))}
            </div>
          ) : (
            <>
              {muted
                ? <Row icon={MuteIcon} testId="info-unmute" label={w.unmute} hint={new Date(conversation.mutedUntil).getUTCFullYear() >= 9000 ? w.mutedForever : undefined} onClick={set({ mute: "off" })} />
                : <Row icon={MuteIcon} testId="info-mute" label={w.mute} onClick={() => setMuteOpen(true)} />}
              <Row icon={PushPinIcon} testId="info-pin" label={pinned ? w.unpin : w.pin} onClick={set({ pinned: !pinned })} />
              <Row icon={ArchiveIcon} testId="info-archive" label={archived ? w.unarchive : w.archive} onClick={set({ archived: !archived })} />
              <Row icon={UnreadIcon} testId="info-unread" label={w.markUnread} onClick={set({ marked_unread: true })} />
              <p className="pb-2 pt-1 text-[12px] text-[#667781]">{w.sharedNote}</p>
            </>
          )}
        </Section>

        {customer && (
          <Section>
            <p className="pb-2 text-[13px] text-[#667781]">{w.store}</p>
            {typeof customer.lifetime_value !== "undefined" && (
              <div className="flex items-center justify-between py-1 text-[15px] text-[#111b21]">
                <span>{w.spent}</span>
                <span data-testid="info-spend" className="tabular-nums">{formatMoney ? formatMoney(Number(customer.lifetime_value || 0)) : Number(customer.lifetime_value || 0)}</span>
              </div>
            )}
            {blocked && <p data-testid="info-blocked" className="py-1 text-[13px] text-[#ea0038]">{w.noBuy} · {w.noBuyHint}</p>}
            <button type="button" data-testid="info-profile" onClick={() => onOpenCustomerProfile?.(conversation)} className="mt-2 w-full rounded-lg bg-[#d9fdd3] py-2 text-[14px] font-medium text-[#025144] hover:bg-[#c8f7c0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">{w.openProfile}</button>
            {onToggleBuyBlock && (
              <button type="button" data-testid="info-buyblock" onClick={() => onToggleBuyBlock(!blocked)} className="mt-2 w-full py-2 text-[14px] text-[#ea0038] hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ea0038]">{blocked ? w.allowBuy : w.blockBuy}</button>
            )}
          </Section>
        )}
      </div>
    </aside>
  );
}
