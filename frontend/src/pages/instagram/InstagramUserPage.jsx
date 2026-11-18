import React from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IG, igCount, igShortTime } from "@/components/instagram/igTheme";
import { IgVerified } from "@/components/instagram/igIcons";
import { formatCurrency } from "@/lib/regional";
import { useInstagramData } from "./useInstagramData";

/** /instagram/u/:customerId — a customer's profile as Instagram shows it in a chat, plus what the shop knows. */
export default function InstagramUserPage() {
  const { customerId } = useParams();
  const { lang, threads } = useInstagramData();
  const isArabic = lang === "ar";
  const { data: customer, isLoading, error } = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api(`/customers/${encodeURIComponent(customerId)}`),
    enabled: Boolean(customerId),
  });
  const chats = threads.filter((row) => row.customerId === customerId);
  const ig = (customer?.identities || []).find((item) => String(item.channel || "").toLowerCase() === "instagram") || {};
  const handle = ig.username || (chats[0]?.handle || "").replace(/^@/, "");

  if (isLoading) return <p role="status" className="p-8 text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "جارٍ التحميل…" : "Loading…"}</p>;
  if (error || !customer) {
    return (
      <div role="alert" className="p-8 text-center text-[14px]">
        <p className="text-[20px] font-semibold">{isArabic ? "عذرًا، هذه الصفحة غير متاحة." : "Sorry, this page isn't available."}</p>
        <Link to="/instagram/direct/inbox" className="mt-3 inline-block font-semibold" style={{ color: IG.blue }}>{isArabic ? "رجوع للرسائل" : "Back to messages"}</Link>
      </div>
    );
  }
  const money = (() => { try { return formatCurrency(Number(customer.lifetime_value || 0)); } catch { return customer.lifetime_value; } })();
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[935px] px-5 pt-8">
        <header className="flex items-center gap-7 pb-10 md:gap-24 md:px-12">
          <IgAvatar src={chats[0]?.avatarUrl} size={150} className="hidden md:inline-block" />
          <IgAvatar src={chats[0]?.avatarUrl} size={77} className="md:hidden" />
          <section className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 dir="ltr" className="flex items-center gap-1.5 text-[20px] font-normal">{handle || customer.name}{ig.verified && <IgVerified size={18} label={isArabic ? "موثّق" : "Verified"} />}</h1>
              {chats[0] && <Link to={`/instagram/direct/t/${encodeURIComponent(chats[0].id)}`} className="rounded-lg px-4 py-[7px] text-[14px] font-semibold hover:bg-[#dbdbdb]" style={{ background: IG.button }}>{isArabic ? "مراسلة" : "Message"}</Link>}
              {handle && <a href={`https://www.instagram.com/${encodeURIComponent(handle)}/`} target="_blank" rel="noreferrer" className="rounded-lg px-4 py-[7px] text-[14px] font-semibold hover:bg-[#dbdbdb]" style={{ background: IG.button }}>{isArabic ? "فتح على إنستغرام" : "View on Instagram"}</a>}
            </div>
            <ul className="mt-5 flex flex-wrap gap-x-10 gap-y-2 text-[16px]">
              {ig.follower_count != null && <li><span className="font-semibold">{igCount(ig.follower_count, lang)}</span> {isArabic ? "متابِع" : "followers"}</li>}
              {ig.follows_you != null && <li style={{ color: IG.secondary }}>{ig.follows_you ? (isArabic ? "يتابعك" : "Follows you") : (isArabic ? "لا يتابعك" : "Doesn't follow you")}</li>}
            </ul>
            <div className="mt-5 text-[14px] leading-[18px]">
              <p dir="auto" className="font-semibold">{customer.name}</p>
              {customer.is_blocked && <p className="mt-1 font-semibold" style={{ color: IG.error }}>{isArabic ? "محظور" : "Blocked"}</p>}
            </div>
          </section>
        </header>
        <section aria-label={isArabic ? "عند المتجر" : "At the shop"} className="border-t py-6" style={{ borderColor: IG.border }}>
          <h2 className="mb-3 text-[12px] font-semibold uppercase tracking-[1px]" style={{ color: IG.secondary }}>{isArabic ? "عند المتجر" : "At the shop"}</h2>
          <dl className="grid grid-cols-2 gap-4 text-[14px] md:grid-cols-4">
            <div><dt style={{ color: IG.secondary }}>{isArabic ? "إجمالي المشتريات" : "Lifetime value"}</dt><dd className="mt-1 font-semibold">{money}</dd></div>
            <div><dt style={{ color: IG.secondary }}>{isArabic ? "عميل منذ" : "Customer since"}</dt><dd className="mt-1 font-semibold">{customer.created_at ? new Date(customer.created_at).toLocaleDateString(isArabic ? "ar-EG" : "en-GB") : "—"}</dd></div>
            {customer.phone && <div><dt style={{ color: IG.secondary }}>{isArabic ? "الهاتف" : "Phone"}</dt><dd dir="ltr" className="mt-1 font-semibold">{customer.phone}</dd></div>}
            {customer.email && <div><dt style={{ color: IG.secondary }}>{isArabic ? "البريد" : "Email"}</dt><dd dir="ltr" className="mt-1 truncate font-semibold">{customer.email}</dd></div>}
          </dl>
        </section>
        <section aria-label={isArabic ? "المحادثات" : "Conversations"} className="border-t py-6" style={{ borderColor: IG.border }}>
          <h2 className="mb-3 text-[12px] font-semibold uppercase tracking-[1px]" style={{ color: IG.secondary }}>{isArabic ? "المحادثات" : "Conversations"}</h2>
          {chats.length === 0
            ? <p className="text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "لا توجد محادثات إنستغرام." : "No Instagram conversations."}</p>
            : chats.map((chat) => (
              <Link key={chat.id} to={`/instagram/direct/t/${encodeURIComponent(chat.id)}`} className="flex items-center justify-between gap-3 rounded-lg px-2 py-2 text-[14px] hover:bg-[#f2f2f2]">
                <span dir="auto" className="truncate">{chat.preview || chat.customer}</span>
                <span className="shrink-0 text-[12px]" style={{ color: IG.secondary }}>{igShortTime(chat.lastAt, lang)}</span>
              </Link>
            ))}
        </section>
      </div>
    </div>
  );
}
