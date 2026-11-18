import React from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useInbox } from "@/pages/inbox/InboxProvider";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";

/** /instagram/profile/:customerId — who this customer is, plus every Instagram chat they have with the shop. */
export default function InstagramProfilePage() {
  const { customerId } = useParams();
  const { lang, convMap } = useInbox();
  const isArabic = lang === "ar";
  const { data: customer, isLoading, error } = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api(`/customers/${encodeURIComponent(customerId)}`),
    enabled: Boolean(customerId),
  });
  const chats = (convMap.instagram || []).filter((row) => row.customerId === customerId);
  const identity = (customer?.identities || []).find((item) => String(item.provider || item.channel || "").toLowerCase() === "instagram");

  if (isLoading) return <p className="p-6 text-[13px] text-muted-foreground">{isArabic ? "جارٍ التحميل…" : "Loading…"}</p>;
  if (error || !customer) {
    return (
      <div role="alert" className="m-6 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
        {isArabic ? "تعذّر تحميل هذا العميل." : "Could not load this customer."}{" "}
        <Link to="/instagram/direct" className="underline">{isArabic ? "رجوع للرسائل" : "Back to messages"}</Link>
      </div>
    );
  }
  return (
    <div dir={isArabic ? "rtl" : "ltr"} className="h-full overflow-y-auto bg-white p-6">
      <div className="mx-auto max-w-2xl space-y-6">
        <header className="flex items-center gap-4">
          {chats[0] ? <ConversationAvatar conversation={chats[0]} className="h-20 w-20 text-[22px]" /> : <div className="grid h-20 w-20 place-items-center rounded-full bg-[#efefef] text-[22px] font-semibold text-[#737373]">{String(customer.name || "?").slice(0, 2).toUpperCase()}</div>}
          <div className="min-w-0">
            <h1 className="truncate text-[20px] font-semibold text-[#262626]">{customer.name}</h1>
            {identity?.value && <p dir="ltr" className="text-[13px] text-[#8e8e8e]">@{String(identity.value).replace(/^@/, "")}</p>}
            {customer.is_blocked && <p className="mt-1 text-[12px] font-semibold text-destructive">{isArabic ? "محظور" : "Blocked"}</p>}
          </div>
        </header>
        <dl className="grid grid-cols-2 gap-3 text-[13px]">
          <div className="rounded-lg border border-[#dbdbdb] p-3"><dt className="text-[#8e8e8e]">{isArabic ? "إجمالي المشتريات" : "Lifetime value"}</dt><dd className="mt-1 font-semibold text-[#262626]">{customer.lifetime_value}</dd></div>
          <div className="rounded-lg border border-[#dbdbdb] p-3"><dt className="text-[#8e8e8e]">{isArabic ? "عميل منذ" : "Customer since"}</dt><dd className="mt-1 font-semibold text-[#262626]">{customer.created_at ? new Date(customer.created_at).toLocaleDateString(isArabic ? "ar-EG" : "en-GB") : "—"}</dd></div>
          {customer.phone && <div className="rounded-lg border border-[#dbdbdb] p-3"><dt className="text-[#8e8e8e]">{isArabic ? "الهاتف" : "Phone"}</dt><dd dir="ltr" className="mt-1 font-semibold text-[#262626]">{customer.phone}</dd></div>}
          {customer.email && <div className="rounded-lg border border-[#dbdbdb] p-3"><dt className="text-[#8e8e8e]">{isArabic ? "البريد" : "Email"}</dt><dd dir="ltr" className="mt-1 truncate font-semibold text-[#262626]">{customer.email}</dd></div>}
        </dl>
        <section aria-label={isArabic ? "المحادثات" : "Conversations"}>
          <h2 className="mb-2 text-[14px] font-semibold text-[#262626]">{isArabic ? "المحادثات" : "Conversations"}</h2>
          {chats.length === 0 ? (
            <p className="text-[13px] text-[#8e8e8e]">{isArabic ? "لا توجد محادثات إنستغرام." : "No Instagram conversations."}</p>
          ) : (
            <ul className="divide-y divide-[#efefef] rounded-lg border border-[#dbdbdb]">
              {chats.map((chat) => (
                <li key={chat.id}><Link to={`/instagram/direct/${encodeURIComponent(chat.id)}`} className="flex items-center justify-between gap-3 px-3 py-2.5 text-[13px] hover:bg-[#fafafa]"><span className="truncate">{chat.preview || chat.customer}</span><span dir="ltr" className="shrink-0 text-[11px] text-[#8e8e8e]">{chat.time}</span></Link></li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
