import React, { useState } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

const EMOJI_CATEGORIES = [
  {
    id: "smileys",
    name: "Smileys",
    icon: "😀",
    emojis: [
      "😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰",
      "😘", "😗", "😙", "😚", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔", "🤐", "🤨",
      "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "🤥", "😔", "😪", "🤤", "😴", "😷", "🤒", "🤕", "🤢",
      "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳", "🥸", "😎", "🤓", "🧐", "😕", "😟", "🙁",
    ],
  },
  {
    id: "gestures",
    name: "Gestures",
    icon: "👍",
    emojis: [
      "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "🤙", "👈", "👉", "👆", "👇", "☝️", "✋", "🤚", "🖐️",
      "🖖", "👋", "👏", "🙌", "👐", "🤲", "🤝", "🙏", "✍️", "💅", "🤳", "💪", "🦾", "🦵", "🦶", "👂",
      "👀", "👁️", "👅", "👄", "💋", "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️",
    ],
  },
  {
    id: "shopping",
    name: "Shopping & Store",
    icon: "🛍️",
    emojis: [
      "🛍️", "🛒", "🏷️", "📦", "💰", "💵", "💳", "🧾", "🎁", "🏪", "🏬", "🚚", "🚛", "🛵", "📱", "💻",
      "✉️", "📞", "⏰", "⏳", "🔑", "🔒", "⭐", "🌟", "✨", "🔥", "💥", "🎉", "🎊", "👗", "👕", "👖",
      "👔", "👠", "👟", "👜", "🎒", "💼", "🕶️", "⌚", "💍", "💎", "💯", "✅", "❌", "⚡", "📢", "💬",
    ],
  },
];


export default function ChannelEmojiStickerPicker({
  isOpen,
  onClose,
  onSelectEmoji,
  lang = "ar",
  isWhatsApp = false,
}) {
  const [activeTab, setActiveTab] = useState("emoji");
  const [activeCategory, setActiveCategory] = useState("smileys");
  const [search, setSearch] = useState("");

  if (!isOpen) return null;
  const isAr = lang === "ar";

  const currentCategoryEmojis = EMOJI_CATEGORIES.find((c) => c.id === activeCategory)?.emojis || [];
  const filteredEmojis = search.trim()
    ? EMOJI_CATEGORIES.flatMap((c) => c.emojis).filter((e) => e.includes(search.trim()))
    : currentCategoryEmojis;

  return (
    <div
      role="dialog"
      aria-label={isAr ? "لوحة الرموز" : "Emoji picker"}
      className={cn(
        "absolute bottom-16 left-3 z-40 w-80 sm:w-96 rounded-2xl shadow-2xl border flex flex-col overflow-hidden animate-in fade-in-50 zoom-in-95",
        isWhatsApp ? "bg-white border-[#d1d7db]" : "bg-card border-border"
      )}
      style={{ height: 320 }}
    >
      {/* Top Header Tabs */}
      <div className="flex items-center justify-between border-b border-border/80 px-2 py-1.5 bg-surface/50">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setActiveTab("emoji")}
            className={cn(
              "px-3 py-1 rounded-lg text-[12px] font-semibold transition-colors",
              activeTab === "emoji" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            )}
          >
            😀 {isAr ? "الرموز" : "Emoji"}
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="h-7 w-7 rounded-full grid place-items-center text-muted-foreground hover:bg-surface hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Search Input */}
      {activeTab === "emoji" && (
        <div className="p-2 border-b border-border/60">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={isAr ? "ابحث في الرموز…" : "Search emoji…"}
              className="w-full h-7 pl-8 pr-2 rounded-lg bg-surface text-[12px] outline-none border border-border/70"
            />
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin p-3">
        {activeTab === "emoji" && (
          <div className="grid grid-cols-8 gap-1.5 text-[22px] select-none">
            {filteredEmojis.map((emoji, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectEmoji(emoji)}
                className="h-9 w-9 rounded-lg hover:bg-surface flex items-center justify-center transition-transform hover:scale-125"
              >
                {emoji}
              </button>
            ))}
          </div>
        )}

      </div>

      {/* Category Icons Bottom Bar (WhatsApp style) */}
      {activeTab === "emoji" && (
        <div className="flex items-center justify-around border-t border-border/80 p-1.5 bg-surface/30">
          {EMOJI_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => { setActiveCategory(cat.id); setSearch(""); }}
              className={cn(
                "h-7 w-7 rounded-md text-[16px] grid place-items-center transition-colors",
                activeCategory === cat.id ? "bg-primary/15 text-primary scale-110" : "opacity-60 hover:opacity-100"
              )}
              title={cat.name}
            >
              {cat.icon}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
