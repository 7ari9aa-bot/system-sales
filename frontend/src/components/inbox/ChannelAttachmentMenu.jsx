import React, { useRef } from "react";
import {
  FileText,
  Image as ImageIcon,
  Camera,
  User,
  BarChart2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function ChannelAttachmentMenu({
  isOpen,
  onClose,
  onFileSelected,
  onSendAction,
  lang = "ar",
  channelId: _channelId = "whatsapp",
}) {
  const fileInputRef = useRef(null);
  const docInputRef = useRef(null);

  if (!isOpen) return null;
  const isAr = lang === "ar";

  function handleFileInputChange(e, type) {
    const file = e.target.files?.[0];
    if (file) {
      onFileSelected(file, type);
      onClose();
    }
  }

  const items = [
    {
      id: "document",
      title: isAr ? "مستند" : "Document",
      color: "bg-[#7f66ff] hover:bg-[#7054f7]",
      icon: FileText,
      onClick: () => docInputRef.current?.click(),
    },
    {
      id: "media",
      title: isAr ? "الصور ومقاطع الفيديو" : "Photos & videos",
      color: "bg-[#007bfc] hover:bg-[#006ee0]",
      icon: ImageIcon,
      onClick: () => fileInputRef.current?.click(),
    },
    {
      id: "camera",
      title: isAr ? "كاميرا" : "Camera",
      color: "bg-[#d3396d] hover:bg-[#c22e5f]",
      icon: Camera,
      onClick: () => fileInputRef.current?.click(),
    },
    {
      id: "contact",
      title: isAr ? "جهة اتصال" : "Contact",
      color: "bg-[#009de2] hover:bg-[#008ecf]",
      icon: User,
      onClick: () => {
        onSendAction?.("👤 بطاقة جهة اتصال متجرنا الرسمية\nالهاتف: +20 101 234 5678");
        onClose();
      },
    },
    {
      id: "poll",
      title: isAr ? "استطلاع رأي" : "Poll",
      color: "bg-[#ffbc38] hover:bg-[#f2b02e]",
      icon: BarChart2,
      onClick: () => {
        onSendAction?.("📊 استطلاع رأي: كيف تقيّم تجربة الشراء معنا اليوم؟\n1. ممتاز ⭐\n2. جيد 👍\n3. بحاجة لتحسين 🔧");
        onClose();
      },
    },
  ];

  return (
    <>
      {/* Hidden File Inputs */}
      <input
        type="file"
        ref={fileInputRef}
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => handleFileInputChange(e, "image")}
      />
      <input
        type="file"
        ref={docInputRef}
        accept=".pdf,.doc,.docx,.xls,.xlsx,.txt"
        className="hidden"
        onChange={(e) => handleFileInputChange(e, "document")}
      />

      {/* Popover */}
      <div
        role="menu"
        aria-label={isAr ? "خيارات المرفقات" : "Attachment options"}
        className="absolute bottom-16 left-3 sm:left-6 z-40 p-2.5 rounded-2xl bg-white dark:bg-card border border-[#e9edef] dark:border-border shadow-2xl flex flex-col gap-2.5 animate-in fade-in-50 slide-in-from-bottom-2 duration-150"
      >
        <div className="flex flex-col gap-2 min-w-[190px]">
          {items.map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={it.onClick}
                className="flex items-center gap-3 p-1.5 rounded-xl hover:bg-[#f5f6f6] dark:hover:bg-surface text-start transition-colors group"
              >
                <span className={cn("h-10 w-10 rounded-full text-white grid place-items-center shrink-0 shadow-sm transition-transform group-hover:scale-105", it.color)}>
                  <Icon className="h-5 w-5" />
                </span>
                <span className="text-[13px] font-medium text-[#111b21] dark:text-foreground">
                  {it.title}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
