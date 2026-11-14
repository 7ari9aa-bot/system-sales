/** The assistant's memory, as the owner sees it: every note, with the right to add, change, delete
 *  one, delete all, and switch the whole thing off. The server decides what is acceptable (it refuses
 *  secrets, instructions, duplicates and a full memory) and writes the reason in Arabic; this panel
 *  shows that reason and never reports a change until the server confirmed it. */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Lightbulb, Pencil, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import {
  cleanNote,
  isFull,
  memoryErrorMessage,
  noteDraftState,
  habitEvidence,
  sourceLabel,
  visibleNotes,
  visibleSuggestions,
} from "@/lib/ownerMemory";

const MEMORY_KEY = ["owner-memory"];
const SUGGESTIONS_KEY = ["owner-memory", "suggestions"];

export default function MemoryPanel({ onClose }) {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const queryClient = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const [editing, setEditing] = React.useState(null); // { id, text }
  const [confirmClear, setConfirmClear] = React.useState(false);
  const [error, setError] = React.useState("");

  const memory = useQuery({
    queryKey: MEMORY_KEY,
    queryFn: () => api("/ai/owner-memory"),
  });

  // Suggestions are only offered while memory is on; the server returns none when it is off.
  const suggestions = useQuery({
    queryKey: SUGGESTIONS_KEY,
    queryFn: () => api("/ai/owner-memory/suggestions"),
    enabled:
      memory.data?.enabled !== false && !memory.isLoading && !memory.isError,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: MEMORY_KEY, exact: true });
    queryClient.invalidateQueries({ queryKey: SUGGESTIONS_KEY, exact: true });
  };
  const fail = (err) => setError(memoryErrorMessage(err, isAr));

  const add = useMutation({
    mutationFn: (content) =>
      api("/ai/owner-memory", { method: "POST", body: { content } }),
    onSuccess: () => {
      setDraft("");
      setError("");
      refresh();
    },
    onError: fail,
  });
  const edit = useMutation({
    mutationFn: ({ id, content }) =>
      api(`/ai/owner-memory/${id}`, { method: "PATCH", body: { content } }),
    onSuccess: () => {
      setEditing(null);
      setError("");
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id) => api(`/ai/owner-memory/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setError("");
      refresh();
    },
    onError: fail,
  });
  const clear = useMutation({
    mutationFn: () => api("/ai/owner-memory", { method: "DELETE" }),
    onSuccess: () => {
      setConfirmClear(false);
      setError("");
      refresh();
    },
    onError: fail,
  });
  // The request carries the period KEY only. The server measures the habit again and saves its own
  // fixed sentence, so nothing typed here (or forged) can become a note.
  const accept = useMutation({
    mutationFn: (period) =>
      api("/ai/owner-memory/suggestions/accept", {
        method: "POST",
        body: { period },
      }),
    onSuccess: () => {
      setError("");
      refresh();
    },
    onError: fail,
  });
  const dismiss = useMutation({
    mutationFn: (period) =>
      api("/ai/owner-memory/suggestions/dismiss", {
        method: "POST",
        body: { period },
      }),
    onSuccess: () => {
      setError("");
      refresh();
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (enabled) =>
      api("/ai/owner-memory/enabled", { method: "PUT", body: { enabled } }),
    onSuccess: () => {
      setError("");
      refresh();
    },
    onError: fail,
  });

  const data = memory.data;
  const notes = visibleNotes(data?.notes);
  const enabled = data?.enabled !== false;
  const full = isFull(notes.length, data?.max_notes);
  const state = noteDraftState(draft, data?.max_chars);
  const busy =
    add.isPending ||
    edit.isPending ||
    remove.isPending ||
    clear.isPending ||
    accept.isPending ||
    dismiss.isPending;
  const offered =
    enabled && !full ? visibleSuggestions(suggestions.data?.suggestions) : [];

  const submitAdd = () => {
    const text = cleanNote(draft, data?.max_chars);
    if (!text || busy) return;
    add.mutate(text);
  };
  const submitEdit = () => {
    const text = cleanNote(editing?.text, data?.max_chars);
    if (!text || busy) return;
    edit.mutate({ id: editing.id, content: text });
  };

  return (
    <aside
      role="dialog"
      aria-label={t("memory.title")}
      className="flex h-full min-h-0 w-full flex-col overflow-hidden border-border bg-card max-lg:rounded-xl max-lg:border max-lg:shadow-sm lg:border-s"
    >
      <header className="flex items-start gap-2.5 border-b border-border px-4 py-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <Brain className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[14px] font-semibold">{t("memory.title")}</h2>
          <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">
            {t("memory.hint")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("memory.close")}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {memory.isLoading ? (
        <p className="p-6 text-center text-[12.5px] text-muted-foreground">
          {t("memory.loading")}
        </p>
      ) : memory.isError ? (
        <p className="p-6 text-center text-[12.5px] text-destructive">
          {t("memory.failed")}
        </p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <label className="flex cursor-pointer items-center justify-between gap-3 border-b border-border px-4 py-2.5 text-[12.5px] select-none">
            <span>{enabled ? t("memory.enabled") : t("memory.disabled")}</span>
            <input
              type="checkbox"
              role="switch"
              checked={enabled}
              disabled={toggle.isPending}
              onChange={(e) => toggle.mutate(e.target.checked)}
              className="accent-[hsl(var(--primary))]"
            />
          </label>

          {offered.length > 0 ? (
            <section
              aria-label={t("memory.suggestions.title")}
              className="border-b border-border bg-primary/5 px-4 py-3"
            >
              <h3 className="flex items-center gap-1.5 text-[12.5px] font-semibold">
                <Lightbulb className="h-3.5 w-3.5 text-primary" />
                {t("memory.suggestions.title")}
              </h3>
              <ul className="mt-2 space-y-2.5">
                {offered.map((item) => (
                  <li key={item.period} data-testid="habit-suggestion">
                    <p className="text-[13px] leading-6">{item.text}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {[
                        habitEvidence(item.count, isAr),
                        t("memory.suggestions.note"),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <div className="mt-1.5 flex gap-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => accept.mutate(item.period)}
                        className="rounded-md bg-primary px-3 py-1 text-[12px] font-medium text-primary-foreground disabled:opacity-50"
                      >
                        {t("memory.suggestions.accept")}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => dismiss.mutate(item.period)}
                        className="rounded-md border border-border px-3 py-1 text-[12px] disabled:opacity-50"
                      >
                        {t("memory.suggestions.dismiss")}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {error ? (
            <p
              role="alert"
              className="border-b border-border bg-destructive/10 px-4 py-2 text-[12px] text-destructive"
            >
              {error}
            </p>
          ) : null}

          <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {notes.length === 0 ? (
              <li className="px-2 py-8 text-center text-[12.5px] leading-6 text-muted-foreground">
                {t("memory.empty")}
              </li>
            ) : (
              notes.map((note) => (
                <li
                  key={note.id}
                  className="rounded-xl border border-border bg-surface/40 p-3"
                >
                  {editing?.id === note.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={editing.text}
                        onChange={(e) =>
                          setEditing({ id: note.id, text: e.target.value })
                        }
                        rows={3}
                        className="w-full resize-none rounded-lg border border-border bg-card p-2 text-[13px] outline-none focus:border-primary/40"
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={submitEdit}
                          disabled={
                            busy ||
                            !noteDraftState(editing.text, data?.max_chars)
                              .canSend
                          }
                          className="rounded-lg bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground disabled:opacity-50"
                        >
                          {t("memory.save")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditing(null)}
                          className="rounded-lg border border-border px-3 py-1.5 text-[12px]"
                        >
                          {t("memory.cancel")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="whitespace-pre-wrap break-words text-[13px] leading-6">
                        {note.content}
                      </p>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <span className="text-[11px] text-muted-foreground">
                          {sourceLabel(note.source, isAr)}
                        </span>
                        <span className="flex gap-1">
                          <button
                            type="button"
                            onClick={() =>
                              setEditing({ id: note.id, text: note.content })
                            }
                            aria-label={t("memory.edit")}
                            className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => remove.mutate(note.id)}
                            disabled={busy}
                            aria-label={t("memory.delete")}
                            className="rounded-lg p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </span>
                      </div>
                    </>
                  )}
                </li>
              ))
            )}
          </ul>

          <div className="space-y-2 border-t border-border p-3">
            {full ? (
              <p className="text-[12px] text-muted-foreground">
                {t("memory.full")}
              </p>
            ) : null}
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={t("memory.addPlaceholder")}
              rows={2}
              disabled={!enabled || full}
              className="w-full resize-none rounded-lg border border-border bg-card p-2 text-[13px] outline-none focus:border-primary/40 disabled:opacity-60"
            />
            <div className="flex items-center justify-between gap-2">
              <span
                className={`text-[11px] ${state.over ? "text-destructive" : "text-muted-foreground"}`}
              >
                {state.remaining === null
                  ? ""
                  : state.over
                    ? `${-state.remaining} ${t("memory.over")}`
                    : `${t("memory.left")} ${state.remaining}`}
              </span>
              <button
                type="button"
                onClick={submitAdd}
                disabled={!enabled || full || busy || !state.canSend}
                className="rounded-lg bg-primary px-3.5 py-1.5 text-[12px] font-medium text-primary-foreground disabled:opacity-50"
              >
                {t("memory.add")}
              </button>
            </div>

            {notes.length > 0 ? (
              confirmClear ? (
                <div className="flex items-center justify-between gap-2 rounded-lg bg-destructive/10 p-2 text-[12px]">
                  <span>{t("memory.clearConfirm")}</span>
                  <span className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => clear.mutate()}
                      disabled={busy}
                      className="rounded-md bg-destructive px-2.5 py-1 text-destructive-foreground disabled:opacity-50"
                    >
                      {t("memory.confirm")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmClear(false)}
                      className="rounded-md border border-border px-2.5 py-1"
                    >
                      {t("memory.cancel")}
                    </button>
                  </span>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmClear(true)}
                  className="text-[11.5px] text-muted-foreground underline-offset-2 hover:text-destructive hover:underline"
                >
                  {t("memory.clearAll")} ({notes.length} {t("memory.count")})
                </button>
              )
            ) : null}
          </div>
        </div>
      )}
    </aside>
  );
}
