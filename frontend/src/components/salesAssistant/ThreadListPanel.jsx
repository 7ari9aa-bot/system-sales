/** Thread list — search, new chat, rename inline, archive/restore, delete
 *  with confirm. Runs inside a drawer on mobile (owned by the page). */

import React from "react";
import { Archive, ArchiveRestore, Check, MessageSquarePlus, Pencil, Trash2, X } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
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
  const [renamingId, setRenamingId] = React.useState(null);
  const [draft, setDraft] = React.useState("");
  const [confirmingId, setConfirmingId] = React.useState(null);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 p-3">
        <button
          type="button"
          onClick={onNew}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground hover:opacity-90 transition-opacity"
        >
          <MessageSquarePlus className="h-4 w-4" />
          {t("salesAssistant.newChat")}
        </button>
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={t("salesAssistant.searchThreads")}
          className="w-full rounded-xl border border-border bg-card px-3 py-2 text-[13px] outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary/40"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {(threads ?? []).length === 0 && (
          <p className="px-2 py-6 text-center text-[12.5px] text-muted-foreground">
            {t("salesAssistant.noThreads")}
          </p>
        )}
        <ul className="space-y-1">
          {(threads ?? []).map((th) => {
            const active = th.id === activeId;
            const renaming = renamingId === th.id;
            return (
              <li key={th.id}>
                <div
                  className={
                    active
                      ? "rounded-xl bg-primary/10 border border-primary/20"
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
                          if (e.key === "Enter" && draft.trim()) {
                            onRename(th, draft.trim());
                            setRenamingId(null);
                          }
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        className="min-w-0 flex-1 rounded-lg border border-border bg-card px-2 py-1 text-[12.5px] outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          if (draft.trim()) onRename(th, draft.trim());
                          setRenamingId(null);
                        }}
                        className="rounded-lg p-1.5 text-success hover:bg-surface"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setRenamingId(null)}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : confirmingId === th.id ? (
                    <div className="flex items-center justify-between gap-1 p-2">
                      <span className="text-[12px] text-destructive">{t("salesAssistant.deleteConfirm")}</span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            onDelete(th);
                            setConfirmingId(null);
                          }}
                          className="rounded-lg bg-destructive/10 px-2 py-1 text-[11.5px] font-medium text-destructive"
                        >
                          {t("salesAssistant.delete")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmingId(null)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                  ) : (
                    <div className="group flex items-center gap-1 px-2.5 py-2">
                      <button
                        type="button"
                        onClick={() => onSelect(th)}
                        className="min-w-0 flex-1 text-start"
                      >
                        <span className="block truncate text-[13px] font-medium">
                          {th.title || t("salesAssistant.untitled")}
                        </span>
                        {th.status === "archived" && (
                          <Badge tone="muted">{t("salesAssistant.archived")}</Badge>
                        )}
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
                        {th.status === "archived" ? (
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
