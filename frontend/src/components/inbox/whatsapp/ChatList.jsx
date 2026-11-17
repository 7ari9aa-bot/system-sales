import React, { useMemo, useState } from "react";
import ChatListRow from "./ChatListRow";
import { ArchiveIcon, BackIcon, SearchIcon } from "./icons";
import { tabCounts, visibleRows } from "./chatListState";
import { MAX_PINNED } from "./ChatListMenu";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: { search: "ابحث أو ابدأ محادثة جديدة", all: "الكل", unread: "غير مقروءة", waiting: "بانتظار الرد", approvals: "موافقات", archived: "المؤرشفة", back: "رجوع", empty: "لا توجد محادثات", emptyArchive: "لا توجد محادثات مؤرشفة", emptyUnread: "لا توجد محادثات غير مقروءة", noMatch: "لا نتائج مطابقة", tabs: "تصفية المحادثات" },
  en: { search: "Search or start a new chat", all: "All", unread: "Unread", waiting: "Waiting", approvals: "Approvals", archived: "Archived", back: "Back", empty: "No conversations", emptyArchive: "No archived chats", emptyUnread: "No unread chats", noMatch: "No matching chats", tabs: "Filter chats" },
};

/**
 * The WhatsApp-style chat list: search, filter tabs, an Archived entry, pinned
 * chats on top. It owns only view state (tab, query, archive view); the rows and
 * every change come from the caller, which talks to the server.
 */
export default function ChatList({ rows, activeId, lang = "ar", onOpen, onChange, ConversationAvatar, footer }) {
  const w = WORDS[lang] || WORDS.en;
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [archiveView, setArchiveView] = useState(false);

  const counts = useMemo(() => tabCounts(rows), [rows]);
  const shown = useMemo(() => visibleRows(rows, { tab: archiveView ? "all" : tab, query, archived: archiveView }), [rows, tab, query, archiveView]);
  const pinnedCount = useMemo(() => rows.filter((r) => r.pinnedAt && !r.archivedAt).length, [rows]);
  const tabs = ["all", "unread", "waiting", "approvals"];

  const emptyText = query.trim() ? w.noMatch : archiveView ? w.emptyArchive : tab === "unread" ? w.emptyUnread : w.empty;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-white" data-testid="chat-list">
      <div className="space-y-2 border-b border-[#d1d7db] px-3 pb-0 pt-3">
        {archiveView ? (
          <div className="flex items-center gap-2 pb-2">
            <button type="button" onClick={() => setArchiveView(false)} aria-label={w.back} className="grid h-8 w-8 place-items-center rounded-full text-[#54656f] hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
              <BackIcon size={20} className={lang === "ar" ? "rotate-180" : ""} />
            </button>
            <h2 className="text-[17px] font-semibold text-[#111b21]">{w.archived}</h2>
          </div>
        ) : null}
        <div className="relative">
          <SearchIcon size={16} className={cn("absolute top-1/2 -translate-y-1/2 text-[#667781]", lang === "ar" ? "right-3" : "left-3")} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            dir={lang === "ar" ? "rtl" : "ltr"}
            aria-label={w.search}
            placeholder={w.search}
            className={cn("h-9 w-full rounded-lg border border-[#f0f2f5] bg-[#f0f2f5] text-[13.5px] placeholder:text-[#667781] focus:border-[#00a884] focus:outline-none", lang === "ar" ? "pr-9 pl-3 text-right" : "pl-9 pr-3")}
          />
        </div>
        {!archiveView && (
          <div role="tablist" aria-label={w.tabs} className="flex gap-1.5 overflow-x-auto pb-2.5">
            {tabs.map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                data-testid={`tab-${id}`}
                onClick={() => setTab(id)}
                className={cn(
                  "whitespace-nowrap rounded-full px-3 py-1 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]",
                  tab === id ? "bg-[#d9fdd3] font-medium text-[#025144]" : "bg-[#f0f2f5] text-[#54656f] hover:bg-[#e9edef]",
                )}
              >
                {w[id]}
                {id !== "all" && counts[id] > 0 && <span className="ms-1 tabular-nums">{counts[id]}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin" data-testid="chat-list-scroll">
        {!archiveView && counts.archived > 0 && !query.trim() && (
          <button type="button" data-testid="open-archive" onClick={() => setArchiveView(true)} className="flex w-full items-center gap-4 border-b border-[#e9edef] px-5 py-3 text-start text-[14.5px] text-[#111b21] hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#00a884]">
            <ArchiveIcon size={20} className="text-[#00a884]" />
            <span className="flex-1">{w.archived}</span>
            <span className="text-[12.5px] tabular-nums text-[#00a884]">{counts.archived}</span>
          </button>
        )}
        {shown.length === 0 ? (
          <p className="px-4 py-10 text-center text-[13px] text-[#667781]">{emptyText}</p>
        ) : (
          shown.map((row) => (
            <ChatListRow
              key={row.id}
              row={row}
              active={row.id === activeId}
              lang={lang}
              pinnedCount={pinnedCount}
              ConversationAvatar={ConversationAvatar}
              onOpen={() => onOpen(row)}
              onChange={(body) => onChange(row, body)}
            />
          ))
        )}
        {footer}
      </div>
    </div>
  );
}

export { MAX_PINNED };
