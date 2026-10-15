/** Thread list — search, new chat, rename inline, archive/restore, delete
 *  with confirm. Rows carry the FIHRIST avatar tile and a relative timestamp;
 *  archived threads dim instead of hiding, so state is always legible. */

import React from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  MessageSquare,
  MessageSquarePlus,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useFormatters } from "@/lib/dates";
import { useT } from "@/lib/i18n";

export default function ThreadListPanel({
  threads,
  activeId,
  onSelect,
  onNew,
  onRename,
  onArchive,
  onRestore,
  onDelete,
  search,
  onSearchChange,
}) {
  const t = useT();
  const { ago } = useFormatters();
  const [renamingId, setRenamingId] = React.useState(null);
  const [draft, setDraft] = React.useState("");
  const [confirmingId, setConfirmingId] = React.useState(null);

  const commitRename = (th) => {
    if (draft.trim()) onRename(th, draft.trim());
    setRenamingId(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 p-3">
        <button
          type="button"
          onClick={onNew}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-primary px-3 py-2.5 text-[13px] font-semibold text-primary-foreground shadow-sm hover:opacity-90 active:scale-[0.99] transition-all"
        >
          <MessageSquarePlus className="h-4 w-4" />
          {t("salesAssistant.newChat")}
        </button>
        <div className="relative">
          <input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t("salesAssistant.searchThreads")}
            className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-primary/25 focus:border-primary/40 transition-shadow"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {(threads ?? []).length === 0 && (
          <div className="px-3 py-8 text-center">
            <span className="mx-auto grid h-9 w-9 place-items-center rounded-xl bg-surface text-muted-foreground">
              <MessageSquare className="h-4.5 w-4.5" />
            </span>
            <p className="mt-2 text-[12.5px] text-muted-foreground">{t("salesAssistant.noThreads")}</p>
          </div>
        )}
        <ul className="space-y-1">
          {(threads ?? []).map((th) => {
            const active = th.id === activeId;
            const renaming = renamingId === th.id;
            const archived = th.status === "archived";
            return (
              <li key={th.id} className="animate-fade-in">
                <div
                  className={
                    active
                      ? "rounded-xl border border-primary/25 bg-primary/[0.07]"
                      : "rounded-xl border border-transparent hover:bg-surface transition-colors"
                  }
                >
                  {renaming ? (
                    <div className="flex items-center gap-1 p-1.5">
                      <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(th);
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        className="min-w-0 flex-1 rounded-lg border border-border bg-card px-2 py-1 text-[12.5px] outline-none focus:ring-1 focus:ring-primary/40"
                      />
                      <button
                        type="button"
                        onClick={() => commitRename(th)}
                        title={t("salesAssistant.rename")}
                        className="rounded-lg p-1.5 text-success hover:bg-card"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setRenamingId(null)}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-card"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : confirmingId === th.id ? (
                    <div className="flex items-center justify-between gap-1 p-2">
                      <span className="text-[12px] font-medium text-destructive">
                        {t("salesAssistant.deleteConfirm")}
                      </span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            onDelete(th);
                            setConfirmingId(null);
                          }}
                          className="rounded-lg bg-destructive px-2.5 py-1 text-[11.5px] font-semibold text-white"
                        >
                          {t("salesAssistant.delete")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmingId(null)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-card"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                  ) : (
                    <div className="group flex items-center gap-2 px-2 py-2">
                      <span
                        className={
                          archived
                            ? "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface text-muted-foreground/50"
                            : active
                              ? "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/15 text-primary"
                              : "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface text-muted-foreground"
                        }
                      >
                        <MessageSquare className="h-4 w-4" />
                      </span>
                      <button
                        type="button"
                        onClick={() => onSelect(th)}
                        className="min-w-0 flex-1 text-start"
                      >
                        <span
                          className={`block truncate text-[13px] ${
                            archived ? "text-muted-foreground" : "font-medium"
                          }`}
                        >
                          {th.title || t("salesAssistant.untitled")}
                        </span>
                        <span className="block truncate text-[11px] text-muted-foreground/80">
                          {th.last_message_at ? ago(th.last_message_at) : ago(th.created_at)}
                          {archived ? ` · ${t("salesAssistant.archived")}` : ""}
                        </span>
                      </button>
                      <span className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                        <button
                          type="button"
                          title={t("salesAssistant.rename")}
                          onClick={() => {
                            setRenamingId(th.id);
                            setDraft(th.title || "");
                          }}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-card"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        {archived ? (
                          <button
                            type="button"
                            title={t("salesAssistant.restore")}
                            onClick={() => onRestore(th)}
                            className="rounded-lg p-1.5 text-muted-foreground hover:bg-card"
                          >
                            <ArchiveRestore className="h-3.5 w-3.5" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            title={t("salesAssistant.archive")}
                            onClick={() => onArchive(th)}
                            className="rounded-lg p-1.5 text-muted-foreground hover:bg-card"
                          >
                            <Archive className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          title={t("salesAssistant.delete")}
                          onClick={() => setConfirmingId(th.id)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-card hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
