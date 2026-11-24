import React from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Plug, RefreshCw } from "lucide-react";
import { useCoexistenceStatus } from "@/hooks/useCoexistenceStatus";

/**
 * The one strip the inbox shows about the WhatsApp Business app link.
 *
 * Coexistence means the merchant keeps working in their phone app while FIHRIST mirrors it, so
 * the two things that go wrong are invisible from a conversation: the number stopped being
 * connected (Meta removed the partner), and the history/contacts Meta is still sending has not
 * finished. Both are channel facts, not conversation facts, and both used to live only on the
 * settings screen. A thread that quietly stops updating is how an owner loses trust in the mirror.
 */
const WORDS = {
  ar: {
    disconnected: "الرقم مش متوصل بفهرست دلوقتي",
    reconnect: "اربط الرقم تاني",
    reason: "السبب من Meta",
    historyProgress: "بنجيب سجل المحادثات من تطبيق واتساب",
    contactsProgress: "بنجيب جهات الاتصال من تطبيق واتساب",
    saved: "رسالة اتجابت",
    deadline: "لازم تخلص قبل",
    notShared: "اخترت إنك ما تشاركش سجل المحادثات — التطبيق وفهرست شغالين عادي",
    failed: "Meta وقفت مزامنة البيانات. اربط الرقم تاني للمحاولة",
  },
  en: {
    disconnected: "This number is not connected to FIHRIST right now",
    reconnect: "Reconnect the number",
    reason: "Meta's reason",
    historyProgress: "Importing your chat history from the WhatsApp Business app",
    contactsProgress: "Importing your contacts from the WhatsApp Business app",
    saved: "messages imported",
    deadline: "finishes by",
    notShared: "You chose not to share chat history. The app and FIHRIST both work",
    failed: "Meta stopped the data sync. Re-link the number to try again",
  },
};

/** Which half of the sync is worth a bar, and how far along it is. */
export function syncProgress(status) {
  if (!status) return null;
  const history = status.history;
  const contacts = status.contacts;
  const running = [history, contacts].find((run) => run && run.state !== "completed" && run.state !== "not_shared");
  const run = running || history || contacts;
  if (!run) return null;
  return {
    kind: run.sync_type === "history" ? "history" : "contacts",
    percent: Math.max(0, Math.min(100, Number(run.progress) || 0)),
    stored: Number(run.messages_stored) || 0,
  };
}

export default function CoexistenceBanner({ lang = "ar", status: provided, pollMs }) {
  const live = useCoexistenceStatus({ enabled: provided === undefined, pollMs });
  const status = provided === undefined ? live.status : provided;
  if (!status) return null;

  const w = WORDS[lang] || WORDS.en;
  const ar = lang === "ar";

  if (status.offboarded || status.connected === false) {
    return (
      <div
        data-testid="coexistence-banner"
        data-tone="disconnected"
        role="status"
        className="flex shrink-0 flex-wrap items-center gap-2 border-b border-red-200 bg-red-50 px-4 py-2 text-[12.5px] text-red-800"
      >
        <Plug className="h-4 w-4 shrink-0" />
        <span className="font-semibold">{w.disconnected}</span>
        {(status.disconnect_reason || status.disconnect_event) && (
          <span dir="auto" className="text-red-700/80">
            {w.reason}: {status.disconnect_reason || status.disconnect_event}
          </span>
        )}
        <Link
          to="/settings/channels"
          className="ms-auto inline-flex items-center gap-1 rounded-md border border-red-300 bg-white px-2 py-1 font-semibold text-red-800 hover:bg-red-100"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {w.reconnect}
        </Link>
      </div>
    );
  }

  const state = String(status.sync_state || "");
  if (state === "HISTORY_NOT_SHARED") {
    return (
      <div
        data-testid="coexistence-banner"
        data-tone="not-shared"
        role="status"
        className="shrink-0 border-b border-[color:var(--wa-divider)] bg-[var(--wa-bg-panel)] px-4 py-2 text-[12px] text-[color:var(--wa-text-secondary)]"
      >
        {w.notShared}
      </div>
    );
  }

  if (state === "SYNC_FAILED") {
    return (
      <div
        data-testid="coexistence-banner"
        data-tone="failed"
        role="status"
        className="flex shrink-0 flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-[12.5px] text-amber-900"
      >
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>{w.failed}</span>
        <Link to="/settings/channels" className="ms-auto font-semibold underline">
          {w.reconnect}
        </Link>
      </div>
    );
  }

  if (status.ready) return null;

  const progress = syncProgress(status);
  const label = (status.sync_label && (status.sync_label[lang] || status.sync_label.en)) || (progress?.kind === "history" ? w.historyProgress : w.contactsProgress);
  const percent = progress?.percent || 0;

  return (
    <div
      data-testid="coexistence-banner"
      data-tone="syncing"
      role="status"
      className="shrink-0 border-b border-[color:var(--wa-divider)] bg-[var(--wa-bg-panel)] px-4 py-2 text-[12px] text-[color:var(--wa-text)]"
    >
      <div className="flex flex-wrap items-center gap-2">
        <RefreshCw className="h-3.5 w-3.5 shrink-0 animate-spin text-[color:var(--wa-green)]" aria-hidden="true" />
        <span className="font-medium" dir="auto">{label}</span>
        <span className="text-[color:var(--wa-text-secondary)] tabular-nums" dir="ltr">{percent}%</span>
        {progress?.stored > 0 && (
          <span className="text-[color:var(--wa-text-secondary)] tabular-nums" dir="auto">
            · {progress.stored} {w.saved}
          </span>
        )}
        {status.deadline_at && (
          <span className="ms-auto text-[color:var(--wa-text-secondary)]" dir="auto">
            {w.deadline} <span dir="ltr">{new Date(status.deadline_at).toLocaleString(ar ? "ar-EG" : "en-GB", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}</span>
          </span>
        )}
      </div>
      <div
        data-testid="coexistence-progress"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
        className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-[var(--wa-bg-hover)]"
      >
        <div className="h-full rounded-full bg-[color:var(--wa-green)] transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
