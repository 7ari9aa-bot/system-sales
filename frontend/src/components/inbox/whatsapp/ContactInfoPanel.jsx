import React, { useEffect, useRef, useState } from "react";
import { ArchiveIcon, ClockIcon, CloseIcon, FileIcon, MuteIcon, PushPinIcon, UnreadIcon } from "./icons";
import { formatLeft, replyWindow } from "./replyWindow";
import { countsOf, displayPhone, docsOf, mediaOf, sharedLinksOf } from "./contactInfo";
import { isMuted } from "./chatListState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: {
    title: "معلومات جهة الاتصال", close: "إغلاق", aboutPhone: "رقم الهاتف", windowOpen: "يمكنك الرد مجانًا. تتبقى", windowClosing: "تنتهي نافذة الرد بعد", windowClosed: "انتهت نافذة الرد. الرد بقالب معتمد فقط", windowNever: "لم يراسلنا العميل بعد", media: "الوسائط", docs: "المستندات", links: "الروابط",
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
    title: "Contact info", aboutPhone: "Phone number", windowOpen: "You can reply freely. Left:", windowClosing: "Reply window ends in", windowClosed: "Reply window closed. Approved templates only", windowNever: "The customer has not written yet", close: "Close", media: "Media", docs: "Docs", links: "Links",
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
  return <section className={cn("bg-[var(--wa-bg-panel)] px-7 py-4", className)}>{children}</section>;
}

function Row({ icon: Icon, label, hint, onClick, testId, danger, disabled }) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className={cn("flex w-full items-center gap-5 py-2.5 text-start text-[15px] hover:bg-[var(--wa-bg-hover)] focus-visible:bg-[var(--wa-bg-hover)] focus-visible:outline-none disabled:opacity-50", danger ? "text-[color:var(--wa-danger)]" : "text-[color:var(--wa-text)]")}
    >
      <Icon size={20} className={danger ? "text-[color:var(--wa-danger)]" : "text-[color:var(--wa-text-icon)]"} />
      <span className="min-w-0 flex-1">
        <span className="block">{label}</span>
        {hint && <span className="block text-[12.5px] text-[color:var(--wa-text-secondary)]">{hint}</span>}
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
export default function ContactInfoPanel({ conversation, lang = "ar", now, customer = null, onClose, onChange, onToggleBuyBlock, onOpenCustomerProfile, onOpenImage, formatMoney }) {
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
  const windowInfo = replyWindow(conversation.lastCustomerMessageAt, now);
  const left = formatLeft(windowInfo.msLeft, lang);
  const windowLine = windowInfo.state === "open" ? `${w.windowOpen} ${left}` : windowInfo.state === "closing" ? `${w.windowClosing} ${left}` : windowInfo.state === "closed" ? w.windowClosed : w.windowNever;

  return (
    <aside
      ref={ref}
      tabIndex={-1}
      role="complementary"
      aria-label={w.title}
      data-testid="contact-info"
      dir={lang === "ar" ? "rtl" : "ltr"}
      className="absolute inset-y-0 end-0 z-40 flex w-full flex-col overflow-hidden bg-[var(--wa-bg-panel)] outline-none sm:w-[308px] sm:border-s sm:border-[color:var(--wa-divider)]"
    >
      <header className="flex h-[59px] shrink-0 items-center gap-5 bg-[var(--wa-bg-panel)] px-4 text-[color:var(--wa-text)]">
        <button type="button" onClick={onClose} aria-label={w.close} data-testid="contact-close" className="grid h-9 w-9 place-items-center rounded-full text-[color:var(--wa-text-icon)] hover:bg-[var(--wa-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">
          <CloseIcon size={20} />
        </button>
        <h3 className="text-[16px] font-medium">{w.title}</h3>
      </header>

      <div className="flex-1 overflow-y-auto scrollbar-thin pb-4">
        <Section className="flex flex-col items-center gap-1 py-6">
          <div className="grid h-[80px] w-[80px] max-w-full place-items-center rounded-full text-[26px] font-semibold text-[color:var(--wa-text-icon)]" style={{ background: "#ffdae7" }} aria-hidden="true">
            {conversation.initials}
          </div>
          <h4 dir="auto" data-testid="contact-name" className="mt-3 text-[22px] text-[color:var(--wa-text)]">{conversation.customer}</h4>
          {phone && <div dir="ltr" data-testid="contact-phone" className="text-[16px] text-[color:var(--wa-text-secondary)]">{phone}</div>}
          {email && <div dir="ltr" className="text-[14px] text-[color:var(--wa-text-secondary)]">{email}</div>}
        </Section>

        {(phone || windowLine) && (
          <Section data-testid="info-about">
            <p className="pb-1 text-[13px] text-[color:var(--wa-text-secondary)]">{w.aboutPhone}</p>
            {phone && <div dir="ltr" data-testid="info-about-phone" className="py-1 text-start text-[16px] text-[color:var(--wa-text)]">{phone}</div>}
            {windowLine && (
              <div data-testid="info-window" data-window={windowInfo.state} className={cn("flex items-center gap-2 py-1 text-[14px]", windowInfo.state === "closed" ? "text-[color:var(--wa-warn)]" : "text-[color:var(--wa-green)]")}>
                <ClockIcon size={16} aria-hidden="true" />
                <span>{windowLine}</span>
              </div>
            )}
          </Section>
        )}

        <Section className="pb-2">
          <div className="flex w-full items-center justify-between py-1 text-[14px] text-[color:var(--wa-text-secondary)]">
            <span>{w.mediaLinksDocs}</span>
            <span className="tabular-nums">{total}</span>
          </div>
          <div role="tablist" className="mt-1 flex gap-4 border-b border-[color:var(--wa-bg-chip)]">
            {["media", "docs", "links"].map((id) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} data-testid={`info-tab-${id}`} onClick={() => setTab(id)}
                className={cn("-mb-px border-b-2 pb-2 pt-1 text-[13.5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]", tab === id ? "border-[color:var(--wa-green)] font-medium text-[color:var(--wa-header)]" : "border-transparent text-[color:var(--wa-text-secondary)]")}>
                {w[id]} <span className="tabular-nums">{counts[id]}</span>
              </button>
            ))}
          </div>
          <div className="py-3" data-testid="info-body">
            {tab === "media" && (media.length ? (
              <div className="grid grid-cols-3 gap-1">
                {media.slice(0, 30).map((item) => (
                  <button key={item.id} type="button" data-testid="info-media" onClick={() => onOpenImage?.(item.id)} className="aspect-square overflow-hidden rounded bg-[var(--wa-bg-chip)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">
                    {item.kind === "video" ? <video src={item.url} className="h-full w-full object-cover" muted preload="metadata" /> : <img src={item.url} alt="" loading="lazy" className="h-full w-full object-cover" />}
                  </button>
                ))}
              </div>
            ) : <p className="py-3 text-center text-[13px] text-[color:var(--wa-text-secondary)]">{w.noMedia}</p>)}
            {tab === "docs" && (docs.length ? (
              <ul>{docs.map((d) => (
                <li key={d.id}><a href={d.url} target="_blank" rel="noopener noreferrer" data-testid="info-doc" className="flex items-center gap-3 py-2 text-[14px] text-[color:var(--wa-text)] hover:bg-[var(--wa-bg-hover)]"><FileIcon size={20} className="text-[color:var(--wa-text-icon)]" /><span dir="auto" className="truncate">{d.name || w.docs}</span></a></li>
              ))}</ul>
            ) : <p className="py-3 text-center text-[13px] text-[color:var(--wa-text-secondary)]">{w.noDocs}</p>)}
            {tab === "links" && (links.length ? (
              <ul>{links.map((l) => (
                <li key={l.id}><a href={l.url} target="_blank" rel="noopener noreferrer" data-testid="info-link" className="block py-2 hover:bg-[var(--wa-bg-hover)]"><span dir="ltr" className="block truncate text-[14px] text-[#027eb5]">{l.url}</span><span dir="ltr" className="block text-[12.5px] text-[color:var(--wa-text-secondary)]">{l.host}</span></a></li>
              ))}</ul>
            ) : <p className="py-3 text-center text-[13px] text-[color:var(--wa-text-secondary)]">{w.noLinks}</p>)}
          </div>
        </Section>

        <Section className="py-2">
          <p className="pb-1 pt-2 text-[13px] text-[color:var(--wa-text-secondary)]">{w.chatSettings}</p>
          {muteOpen ? (
            <div role="group" aria-label={w.muteFor}>
              <p className="px-1 py-1 text-[13px] text-[color:var(--wa-text-secondary)]">{w.muteFor}</p>
              {["8h", "1w", "always"].map((d) => (
                <button key={d} type="button" data-testid={`info-mute-${d}`} onClick={() => { onChange?.({ mute: d }); setMuteOpen(false); }} className="block w-full py-2.5 text-start text-[15px] hover:bg-[var(--wa-bg-hover)]">{w[d]}</button>
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
              <p className="pb-2 pt-1 text-[12px] text-[color:var(--wa-text-secondary)]">{w.sharedNote}</p>
            </>
          )}
        </Section>

        {customer && (
          <Section>
            <p className="pb-2 text-[13px] text-[color:var(--wa-text-secondary)]">{w.store}</p>
            {typeof customer.lifetime_value !== "undefined" && (
              <div className="flex items-center justify-between py-1 text-[15px] text-[color:var(--wa-text)]">
                <span>{w.spent}</span>
                <span data-testid="info-spend" className="tabular-nums">{formatMoney ? formatMoney(Number(customer.lifetime_value || 0)) : Number(customer.lifetime_value || 0)}</span>
              </div>
            )}
            {blocked && <p data-testid="info-blocked" className="py-1 text-[13px] text-[color:var(--wa-danger)]">{w.noBuy} · {w.noBuyHint}</p>}
            <button type="button" data-testid="info-profile" onClick={() => onOpenCustomerProfile?.(conversation)} className="mt-2 w-full rounded-lg bg-[var(--wa-pill-active)] py-2 text-[14px] font-medium text-[color:var(--wa-green-text)] hover:bg-[#c8f7c0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">{w.openProfile}</button>
            {onToggleBuyBlock && (
              <button type="button" data-testid="info-buyblock" onClick={() => onToggleBuyBlock(!blocked)} className="mt-2 w-full py-2 text-[14px] text-[color:var(--wa-danger)] hover:bg-[var(--wa-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-danger)]">{blocked ? w.allowBuy : w.blockBuy}</button>
            )}
          </Section>
        )}
      </div>
    </aside>
  );
}
