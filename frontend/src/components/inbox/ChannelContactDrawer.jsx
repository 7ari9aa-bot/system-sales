import React, { useState } from "react";
import {
  X,
  Phone,
  Lock,
  Star,
  Clock,
  ShieldAlert,
  ChevronRight,
  ExternalLink,
  Image as ImageIcon,
  Palette,
  Sparkles,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import { formatCurrency } from "@/lib/regional";

export default function ChannelContactDrawer({
  isOpen,
  onClose,
  channel,
  conversation,
  lang = "ar",
  onOpenCustomerProfile,
}) {
  const [activeMediaTab, setActiveMediaTab] = useState("media"); // media | docs | links
  const [muted, setMuted] = useState(false);
  const [starred, setStarred] = useState(false);

  if (!isOpen || !conversation) return null;

  const isAr = lang === "ar";
  const isWhatsApp = channel.id === "whatsapp";
  const isInstagram = channel.id === "instagram";
  const isMessenger = channel.id === "messenger";
  const isTelegram = channel.id === "telegram";

  const customerName = conversation.customer || (isAr ? "عميل المتجر" : "Store Customer");
  const customerPhone = conversation.phone || conversation.customer_phone || "+20 101 234 5678";
  const handle = conversation.username || (conversation.customer ? `@${conversation.customer.toLowerCase().replace(/\s+/g, "_")}` : "@customer");
  const messages = conversation.messages || [];

  // Extract shared media/images from messages
  const sharedMedia = messages.filter((m) => m.mediaUrl || m.mediaType === "image" || m.text?.includes("🖼️"));

  return (
    <div
      className="absolute inset-y-0 right-0 z-40 w-full sm:w-[360px] md:w-[380px] bg-white dark:bg-card border-l border-border shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-200"
      dir={isAr ? "rtl" : "ltr"}
    >
      {/* ==================== 1. WHATSAPP STYLE ==================== */}
      {isWhatsApp && (
        <div className="flex-1 flex flex-col min-h-0 bg-[#f0f2f5] dark:bg-card text-[#111b21] dark:text-foreground">
          {/* Header */}
          <div className="h-[60px] bg-white dark:bg-surface border-b border-[#e9edef] dark:border-border px-4 flex items-center gap-4 shrink-0">
            <button
              type="button"
              onClick={onClose}
              title={isAr ? "إغلاق" : "Close"}
              className="h-9 w-9 rounded-full grid place-items-center text-[#54656f] hover:bg-[#f5f6f6] dark:hover:bg-card transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
            <h3 className="text-[16px] font-medium text-[#111b21] dark:text-foreground">
              {isAr ? "معلومات جهة الاتصال" : "Contact info"}
            </h3>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-2.5">
            {/* Top Contact Card */}
            <div className="bg-white dark:bg-surface rounded-xl p-5 text-center shadow-xs space-y-2">
              <div
                className="h-24 w-24 rounded-full mx-auto grid place-items-center text-[28px] font-bold shadow-xs"
                style={{ background: conversation.color || "#25D366", color: "#fff" }}
              >
                {conversation.initials || "C"}
              </div>
              <div className="pt-1">
                <h4 className="text-[18px] font-semibold text-[#111b21] dark:text-foreground leading-tight">
                  {customerName}
                </h4>
                <div className="text-[13.5px] text-[#667781] mt-0.5" dir="ltr">
                  {customerPhone}
                </div>
              </div>
            </div>

            {/* About / Status */}
            <div className="bg-white dark:bg-surface rounded-xl p-4 shadow-xs space-y-1">
              <div className="text-[12px] text-[#667781] font-normal">
                {isAr ? "الأخبار / الحالة" : "About"}
              </div>
              <div className="text-[14px] text-[#111b21] dark:text-foreground font-medium">
                {isAr ? "متوفر للتواصل والاستفسارات 🛍️" : "Hey there! I am using WhatsApp."}
              </div>
            </div>

            {/* Media, links and docs */}
            <div className="bg-white dark:bg-surface rounded-xl p-4 shadow-xs space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[13.5px] font-medium text-[#111b21] dark:text-foreground flex items-center gap-2">
                  <ImageIcon className="h-4 w-4 text-[#54656f]" />
                  <span>{isAr ? "الوسائط والروابط والمستندات" : "Media, links and docs"}</span>
                </span>
                <span className="text-[12px] text-[#667781] tabular-nums">{sharedMedia.length || 0}</span>
              </div>
              <div className="flex border-b border-border/40 pb-1.5 text-[12px] gap-4">
                {[
                  { id: "media", label: isAr ? "الوسائط" : "Media" },
                  { id: "docs", label: isAr ? "المستندات" : "Docs" },
                  { id: "links", label: isAr ? "الروابط" : "Links" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveMediaTab(tab.id)}
                    className={cn(
                      "pb-1 font-medium transition-colors",
                      activeMediaTab === tab.id
                        ? "text-[#00a884] border-b-2 border-[#00a884]"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-3 gap-2">
                {activeMediaTab === "media" && sharedMedia.length > 0 ? (
                  sharedMedia.slice(0, 3).map((item, idx) => (
                    <div key={idx} className="h-20 rounded-lg bg-surface border border-border/80 overflow-hidden flex items-center justify-center">
                      {item.mediaUrl ? (
                        <img src={item.mediaUrl} alt="media" className="h-full w-full object-cover" />
                      ) : (
                        <ImageIcon className="h-6 w-6 text-muted-foreground" />
                      )}
                    </div>
                  ))
                ) : (
                  <div className="col-span-3 py-4 text-center text-[12px] text-[#667781]">
                    {activeMediaTab === "media"
                      ? (isAr ? "لا توجد وسائط مشتركة في هذه المحادثة" : "No shared media")
                      : activeMediaTab === "docs"
                      ? (isAr ? "لا توجد مستندات PDF أو ملفات" : "No documents")
                      : (isAr ? "لا توجد روابط ويب مشتركة" : "No shared links")}
                  </div>
                )}
              </div>
            </div>

            {/* Starred Messages */}
            <div
              onClick={() => setStarred(!starred)}
              className="bg-white dark:bg-surface rounded-xl p-4 shadow-xs flex items-center justify-between cursor-pointer hover:bg-black/5 transition-colors"
            >
              <div className="flex items-center gap-3">
                <Star className={cn("h-4 w-4", starred ? "text-amber-500 fill-amber-500" : "text-[#54656f]")} />
                <span className="text-[13.5px] font-medium">{isAr ? "الرسائل المميزة بنجمة" : "Starred messages"}</span>
              </div>
              <span className="text-[12px] text-muted-foreground">{starred ? (isAr ? "مميّزة ⭐" : "Starred ⭐") : <ChevronRight className="h-4 w-4 text-[#8696a0]" />}</span>
            </div>

            {/* Disappearing Messages & Encryption */}
            <div className="bg-white dark:bg-surface rounded-xl p-4 shadow-xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Clock className="h-4 w-4 text-[#54656f]" />
                  <div>
                    <div className="text-[13.5px] font-medium">{isAr ? "الرسائل ذاتية الاختفاء" : "Disappearing messages"}</div>
                    <div className="text-[11.5px] text-[#667781]">{isAr ? "إيقاف" : "Off"}</div>
                  </div>
                </div>
              </div>
              <div className="pt-2 border-t border-[#f0f2f5] dark:border-border flex items-start gap-3">
                <Lock className="h-4 w-4 text-[#54656f] shrink-0 mt-0.5" />
                <div>
                  <div className="text-[13.5px] font-medium">{isAr ? "التشفير التام" : "Encryption"}</div>
                  <div className="text-[11px] text-[#667781] leading-relaxed">
                    {isAr ? "الرسائل والمكالمات مشفرة تماماً بين الطرفين." : "Messages are end-to-end encrypted."}
                  </div>
                </div>
              </div>
            </div>

            {/* Quick CRM 360 link */}
            <div className="bg-white dark:bg-surface rounded-xl p-4 shadow-xs space-y-2 border border-primary/20">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-bold text-primary flex items-center gap-1.5">
                  <Sparkles className="h-4 w-4" />
                  <span>{isAr ? "سجل العميل في المتجر (CRM)" : "Store Customer Profile"}</span>
                </span>
                <span className="text-[12px] font-semibold tabular-nums text-foreground">
                  {formatCurrency(Number(conversation.lifetime_value || 0))}
                </span>
              </div>
              <button
                type="button"
                onClick={() => { onClose(); onOpenCustomerProfile?.(conversation); }}
                className="w-full h-8 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary text-[12px] font-semibold flex items-center justify-center gap-1.5 transition-colors"
              >
                <span>{isAr ? "عرض البروفايل والسجل الكامل 360" : "Open Full 360 Profile"}</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================== 2. INSTAGRAM STYLE ==================== */}
      {isInstagram && (
        <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-card text-[#262626] dark:text-foreground">
          {/* Header */}
          <div className="h-[60px] border-b border-[#dbdbdb] dark:border-border px-4 flex items-center justify-between shrink-0">
            <h3 className="text-[15px] font-bold text-[#262626] dark:text-foreground">
              {isAr ? "التفاصيل" : "Details"}
            </h3>
            <button
              type="button"
              onClick={onClose}
              className="h-8 w-8 rounded-full grid place-items-center text-[#262626] dark:text-foreground hover:bg-[#f5f5f5] dark:hover:bg-surface"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-5">
            {/* Account Profile */}
            <div className="text-center space-y-2 py-3">
              <ConversationAvatar conversation={conversation} className="h-20 w-20 mx-auto text-[22px] ring-2 ring-primary/20 ring-offset-2" />
              <div>
                <h4 className="text-[16px] font-bold leading-tight">{customerName}</h4>
                <div className="text-[13px] text-[#8e8e8e] mt-0.5">{handle}</div>
              </div>
            </div>

            {/* Mute Messages */}
            <div className="flex items-center justify-between py-2 border-b border-[#dbdbdb] dark:border-border">
              <span className="text-[13.5px] font-medium">{isAr ? "كتم الرسائل" : "Mute messages"}</span>
              <button
                type="button"
                onClick={() => setMuted(!muted)}
                className={cn("w-10 h-5 rounded-full p-0.5 transition-colors", muted ? "bg-[#0095f6]" : "bg-[#dbdbdb] dark:bg-surface")}
              >
                <div className={cn("w-4 h-4 rounded-full bg-white transition-transform", muted && "translate-x-5")} />
              </button>
            </div>

            {/* Members in chat */}
            <div className="space-y-3">
              <div className="text-[12.5px] font-semibold text-[#8e8e8e]">{isAr ? "أعضاء المحادثة" : "Members"}</div>
              <div className="flex items-center gap-3">
                <ConversationAvatar conversation={conversation} className="h-10 w-10 text-[13px]" />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold truncate">{customerName}</div>
                  <div className="text-[11.5px] text-[#8e8e8e] truncate">{handle}</div>
                </div>
              </div>
            </div>

            {/* Shared Media */}
            <div className="space-y-2 pt-2">
              <div className="text-[12.5px] font-semibold text-[#8e8e8e]">{isAr ? "الصور والفيديوهات المشتركة" : "Shared media"}</div>
              <div className="grid grid-cols-3 gap-1.5">
                {sharedMedia.length > 0 ? (
                  sharedMedia.slice(0, 6).map((m, idx) => (
                    <div key={idx} className="aspect-square bg-surface rounded-md overflow-hidden">
                      {m.mediaUrl ? <img src={m.mediaUrl} alt="shared" className="h-full w-full object-cover" /> : <div className="h-full grid place-items-center text-xs text-muted-foreground">Photo</div>}
                    </div>
                  ))
                ) : (
                  <div className="col-span-3 text-[12px] text-muted-foreground py-3 text-center">
                    {isAr ? "لا توجد وسائط مشاركة بعد" : "No shared photos"}
                  </div>
                )}
              </div>
            </div>

            {/* CRM Link */}
            <div className="pt-4 border-t border-[#dbdbdb] dark:border-border">
              <button
                type="button"
                onClick={() => { onClose(); onOpenCustomerProfile?.(conversation); }}
                className="w-full h-9 rounded-xl border border-primary/30 bg-primary/5 hover:bg-primary/10 text-primary text-[12.5px] font-semibold flex items-center justify-center gap-2 transition-colors"
              >
                <Sparkles className="h-4 w-4" />
                <span>{isAr ? "فتح بروفايل العميل الشامل (CRM)" : "Customer 360 Records"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================== 3. MESSENGER STYLE ==================== */}
      {isMessenger && (
        <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-card text-[#050505] dark:text-foreground">
          {/* Header */}
          <div className="h-[60px] border-b border-[#e4e6eb] dark:border-border px-4 flex items-center justify-between shrink-0">
            <h3 className="text-[15px] font-bold text-[#050505] dark:text-foreground">
              {isAr ? "تفاصيل المحادثة" : "Chat details"}
            </h3>
            <button
              type="button"
              onClick={onClose}
              className="h-8 w-8 rounded-full grid place-items-center text-[#65676b] hover:bg-[#f0f2f5] dark:hover:bg-surface"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
            <div className="text-center py-4 space-y-2">
              <ConversationAvatar conversation={conversation} className="h-20 w-20 mx-auto text-[22px]" />
              <h4 className="text-[17px] font-bold">{customerName}</h4>
              <div className="text-[12px] text-[#65676b]">Messenger Contact</div>
            </div>

            {/* Customize Chat */}
            <div className="space-y-2 border-t border-[#e4e6eb] dark:border-border pt-3">
              <div className="text-[12px] font-semibold text-[#65676b] uppercase">{isAr ? "تخصيص المحادثة" : "Customize chat"}</div>
              <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-[#f0f2f5] dark:hover:bg-surface cursor-pointer">
                <Palette className="h-4 w-4 text-[#0084ff]" />
                <span className="text-[13px] font-medium">{isAr ? "تغيير الثيم" : "Change theme"}</span>
              </div>
            </div>

            {/* Privacy & Support */}
            <div className="space-y-2 border-t border-[#e4e6eb] dark:border-border pt-3">
              <div className="text-[12px] font-semibold text-[#65676b] uppercase">{isAr ? "الخصوصية والمساعدة" : "Privacy & Support"}</div>
              <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-[#f0f2f5] dark:hover:bg-surface cursor-pointer text-destructive">
                <ShieldAlert className="h-4 w-4" />
                <span className="text-[13px] font-medium">{isAr ? "حظر المستخدم" : "Block"}</span>
              </div>
            </div>

            {/* CRM Link */}
            <div className="pt-3 border-t border-[#e4e6eb] dark:border-border">
              <button
                type="button"
                onClick={() => { onClose(); onOpenCustomerProfile?.(conversation); }}
                className="w-full h-9 rounded-xl bg-primary text-primary-foreground text-[12.5px] font-semibold flex items-center justify-center gap-2"
              >
                <Sparkles className="h-4 w-4" />
                <span>{isAr ? "بروفايل العميل وسجل الطلبات" : "Customer CRM Profile"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ==================== 4. TELEGRAM STYLE ==================== */}
      {isTelegram && (
        <div className="flex-1 flex flex-col min-h-0 bg-white dark:bg-card text-[#222] dark:text-foreground">
          {/* Header */}
          <div className="h-[60px] bg-[#ffffff] dark:bg-surface border-b border-[#e4e9ec] dark:border-border px-4 flex items-center justify-between shrink-0">
            <h3 className="text-[15px] font-medium text-[#222] dark:text-foreground">
              {isAr ? "معلومات المستخدم" : "User info"}
            </h3>
            <button
              type="button"
              onClick={onClose}
              className="h-8 w-8 rounded-full grid place-items-center text-[#707e8b] hover:bg-[#f2f5f7] dark:hover:bg-card"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
            <div className="flex items-center gap-4 py-2">
              <ConversationAvatar conversation={conversation} className="h-16 w-16 text-[20px]" />
              <div className="min-w-0">
                <h4 className="text-[16px] font-medium truncate">{customerName}</h4>
                <div className="text-[12px] text-[#3390ec]">online</div>
              </div>
            </div>

            {/* Details */}
            <div className="space-y-3 pt-2 border-t border-[#e4e9ec] dark:border-border">
              <div className="flex items-center gap-3 text-[13px]">
                <Phone className="h-4 w-4 text-[#707e8b]" />
                <div>
                  <div className="font-medium" dir="ltr">{customerPhone}</div>
                  <div className="text-[11px] text-[#707e8b]">{isAr ? "الهاتف" : "Phone"}</div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-[13px]">
                <User className="h-4 w-4 text-[#707e8b]" />
                <div>
                  <div className="font-medium text-[#3390ec]">{handle}</div>
                  <div className="text-[11px] text-[#707e8b]">{isAr ? "اسم المستخدم" : "Username"}</div>
                </div>
              </div>
            </div>

            {/* CRM Link */}
            <div className="pt-4 border-t border-[#e4e9ec] dark:border-border">
              <button
                type="button"
                onClick={() => { onClose(); onOpenCustomerProfile?.(conversation); }}
                className="w-full h-9 rounded-xl bg-[#2aabee] text-white text-[12.5px] font-semibold flex items-center justify-center gap-2 hover:opacity-90"
              >
                <Sparkles className="h-4 w-4" />
                <span>{isAr ? "سجل العميل في المتجر" : "Customer CRM 360"}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
