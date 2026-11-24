import React, { useState } from "react";
import { AlertTriangle, Gauge, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useCoexistenceStatus } from "@/hooks/useCoexistenceStatus";

/**
 * The live half of the WhatsApp channel card.
 *
 * Settings used to show the sync state captured at link time, which goes stale the moment the
 * first history chunk lands — so the merchant read "about to sync" for as long as the transfer
 * took, and never saw the one state that needs them: a reservation Meta never answered. This card
 * reads the status endpoint (same one the inbox banner uses) and renders the state, both progress
 * bars, a stuck-sync warning with a local reconcile button, and the number's send rate against
 * Meta's 20-per-second cap so a 130429 can be told apart from a real failure.
 */
const WORDS = {
  ar: {
    title: "مزامنة تطبيق WhatsApp Business",
    contacts: "جهات الاتصال",
    history: "سجل المحادثات",
    saved: "رسالة",
    needsAttention: "طلب مزامنة من غير رد",
    reconcile: "اعتبره منتهي واطلب إعادة ربط",
    reconciling: "بنسجّل...",
    age: "من",
    minutes: "دقيقة",
    requestId: "رقم الطلب",
    throughput: "سرعة الإرسال",
    perSecond: "رسالة/ثانية",
    of: "من",
    headroom: "المتاح",
    rateUnknown: "مش مقروءة دلوقتي",
    rateAtCap: "الرقم على الحد الأقصى — إعادة المحاولة هتنجح",
    rateBusy: "قريب من الحد",
    rateOk: "داخل الحد",
    rate130429:
      "خطأ 130429 معناه إن الرقم بعت أكتر من 20 رسالة في الثانية. لو المعدل فوق على الحد، الإرسال كان أسرع من اللازم وإعادة المحاولة هتنجح. لو منخفض، السبب حاجة تانية: رقم مقيّد أو حظر سياسة.",
    declined: "التاجر اختار إنه ما يشاركش سجل المحادثات",
    settledByDeadline: "نافذة الـ24 ساعة خلصت — مفيش بيانات جديدة جاية، وده مش معناه إن القائمة كاملة",
    snapshotReceived: "وصلت أول دفعة جهات اتصال",
  },
  en: {
    title: "WhatsApp Business app sync",
    contacts: "Contacts",
    history: "Chat history",
    saved: "messages",
    needsAttention: "A sync request with no answer",
    reconcile: "Close it and ask for a re-link",
    reconciling: "Recording...",
    age: "for",
    minutes: "min",
    requestId: "Request id",
    throughput: "Sending rate",
    perSecond: "msg/s",
    of: "of",
    headroom: "headroom",
    rateUnknown: "not tracked right now",
    rateAtCap: "This number is at the cap. A retry will succeed",
    rateBusy: "Close to the cap",
    rateOk: "Within the cap",
    rate130429:
      "Error 130429 means this number sent more than 20 messages in one second. At the cap, the send was paced too hard and a retry will succeed. Below it, the cause is something else: a restricted number or a policy block.",
    declined: "The merchant chose not to share chat history",
    settledByDeadline:
      "The 24-hour window closed: nothing more is coming, which is not the same as a complete list",
    snapshotReceived: "The first contact batch arrived",
  },
};

function Bar({ label, run, w }) {
  if (!run) return null;
  const percent = Math.max(0, Math.min(100, Number(run.progress) || 0));
  return (
    <div className="flex flex-col gap-1" data-testid={`sync-run-${run.sync_type}`}>
      <div className="flex items-center justify-between text-[11.5px] text-slate-600">
        <span>{label}</span>
        <span className="tabular-nums">
          {percent}% · {Number(run.messages_stored) || 0} {w.saved}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${percent}%` }} />
      </div>
      {run.settled_by === "deadline" && (
        <p className="text-[10.5px] leading-4 text-slate-500">{w.settledByDeadline}</p>
      )}
      {run.snapshot_received_at && run.state !== "completed" && (
        <p className="text-[10.5px] leading-4 text-slate-500">{w.snapshotReceived}</p>
      )}
    </div>
  );
}

function Throughput({ throughput, w }) {
  if (!throughput) return null;
  const current = throughput.current;
  const state = throughput.state || "unknown";
  const tone =
    state === "at_cap" ? "text-destructive" : state === "busy" ? "text-amber-700" : "text-slate-600";
  const sentence =
    state === "at_cap" ? w.rateAtCap : state === "busy" ? w.rateBusy : state === "ok" ? w.rateOk : null;
  return (
    <div className="flex flex-col gap-1" data-testid="whatsapp-throughput">
      <div className="flex items-center justify-between text-[11.5px] text-slate-600">
        <span className="inline-flex items-center gap-1">
          <Gauge className="h-3.5 w-3.5" />
          {w.throughput}
        </span>
        <span className={`tabular-nums ${tone}`} data-testid="throughput-value">
          {current === null || current === undefined
            ? w.rateUnknown
            : `${current} ${w.of} ${throughput.limit_per_second} ${w.perSecond}`}
        </span>
      </div>
      {current !== null && current !== undefined && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
          <div
            className={`h-full rounded-full ${state === "at_cap" ? "bg-destructive" : state === "busy" ? "bg-amber-500" : "bg-emerald-500"}`}
            style={{
              width: `${Math.min(100, (Number(current) / (Number(throughput.limit_per_second) || 20)) * 100)}%`,
            }}
          />
        </div>
      )}
      {sentence && <p className={`text-[10.5px] leading-4 ${tone}`}>{sentence}</p>}
      <p className="text-[10.5px] leading-4 text-slate-500" data-testid="throughput-explainer">
        {w.rate130429}
      </p>
    </div>
  );
}

export default function WhatsAppSyncCard({ lang = "ar", status: provided, pollMs }) {
  const live = useCoexistenceStatus({ enabled: provided === undefined, pollMs });
  // The reconcile answer wins over the polled copy: it is newer than the last poll, and the run is
  // settled (failed) afterwards, so the hook stops asking anyway.
  const [override, setOverride] = useState(null);
  const [busy, setBusy] = useState(false);

  const effective = override || (provided === undefined ? live.status : provided);
  if (!effective) return null;
  const w = WORDS[lang] || WORDS.en;
  const attention = effective.contacts?.attention || effective.history?.attention || null;
  const stuckHalf = effective.contacts?.needs_attention ? "contacts" : "history";

  const reconcile = async () => {
    setBusy(true);
    try {
      const fresh = await api("/integrations/whatsapp/coexistence-reconcile", {
        method: "POST",
        body: { sync_type: stuckHalf, note: "closed from the channel settings card" },
      });
      if (fresh) setOverride(fresh);
    } catch {
      // A diagnostic action that fails must not break the card; the warning stays visible.
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="flex w-full max-w-md flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3"
      data-testid="whatsapp-sync-card"
      data-state={effective.sync_state}
    >
      <div className="flex items-center justify-between text-[12.5px] font-semibold text-slate-800">
        <span>{w.title}</span>
        <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-medium text-slate-600">
          {(effective.sync_label && (effective.sync_label[lang] || effective.sync_label.en)) || ""}
        </span>
      </div>

      <Bar label={w.contacts} run={effective.contacts} w={w} />
      <Bar label={w.history} run={effective.history} w={w} />

      {effective.history && effective.history.state === "not_shared" && (
        <p className="text-[10.5px] leading-4 text-slate-500">{w.declined}</p>
      )}

      {attention && (
        <div
          className="flex flex-col gap-1 rounded-lg border border-amber-300 bg-amber-50 p-2"
          data-testid="sync-attention"
        >
          <p className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-amber-900">
            <AlertTriangle className="h-3.5 w-3.5" />
            {w.needsAttention}
            {attention.age_seconds ? ` · ${w.age} ${Math.round(attention.age_seconds / 60)} ${w.minutes}` : ""}
          </p>
          <p className="text-[10.5px] leading-4 text-amber-900/90">{attention.reason}</p>
          {attention.request_id && (
            <p className="font-mono text-[10px] text-amber-900/80" dir="ltr">
              {w.requestId}: {attention.request_id}
            </p>
          )}
          <button
            type="button"
            onClick={reconcile}
            disabled={busy}
            className="inline-flex h-7 w-fit items-center gap-1 rounded-md border border-amber-400 bg-white px-2 text-[11px] font-semibold text-amber-900 disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${busy ? "animate-spin" : ""}`} />
            {busy ? w.reconciling : w.reconcile}
          </button>
        </div>
      )}

      <Throughput throughput={effective.throughput} w={w} />
    </div>
  );
}
