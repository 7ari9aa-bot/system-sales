/** "Where the time goes": the assistant's measured speed over the last days, the causes that made
 *  answers slow (how many answers each touched), and the slowest answers with their reasons.
 *  Everything comes from GET /ai/sales-chat/timing, which reads each answer's measured summary. */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Gauge, X } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { seconds } from "./traceView";

const RANGES = [1, 7, 30];

export default function TimingPanel({ onClose }) {
  const t = useT();
  const [days, setDays] = React.useState(7);
  const q = useQuery({
    queryKey: ["sales-chat-timing", days],
    queryFn: () => api(`/ai/sales-chat/timing?days=${days}`),
  });
  const d = q.data;
  return (
    <aside data-testid="timing-panel" className="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-border bg-background lg:rounded-none lg:border-y-0 lg:border-e-0">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Gauge className="h-4 w-4 text-primary" />
        <h2 className="flex-1 text-[14px] font-semibold">{t("salesAssistant.timing.title")}</h2>
        <button type="button" onClick={onClose} aria-label={t("memory.close")} className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex gap-1 px-4 pt-3">
        {RANGES.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={days === n}
            data-testid={`timing-range-${n}`}
            onClick={() => setDays(n)}
            className="rounded-lg border border-border px-2.5 py-1 text-[12px] aria-pressed:bg-primary aria-pressed:text-primary-foreground aria-pressed:border-primary"
          >
            {t("salesAssistant.timing.days").replace("{n}", String(n))}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto scroll-slim px-4 py-3 space-y-4 text-[12.5px]">
        {q.isLoading && <p className="text-muted-foreground">…</p>}
        {q.isError && <p data-testid="timing-error" className="text-destructive">{t("salesAssistant.timing.error")}</p>}
        {d && d.answers === 0 && (
          <p data-testid="timing-empty" className="text-muted-foreground">{t("salesAssistant.timing.empty")}</p>
        )}
        {d && d.answers > 0 && (
          <>
            <div data-testid="timing-totals" className="grid grid-cols-2 gap-2">
              {[
                ["median", d.median_total_ms],
                ["model", d.avg_model_ms],
                ["tools", d.avg_tools_ms],
                ["other", d.avg_other_ms],
              ].map(([k, ms]) => (
                <div key={k} className="rounded-xl bg-surface px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">{t(`salesAssistant.timing.${k}`)}</p>
                  <p className="num text-[15px] font-semibold">{seconds(ms)} {t("salesAssistant.trace.sec")}</p>
                </div>
              ))}
            </div>
            <p className="num text-[11.5px] text-muted-foreground">
              {t("salesAssistant.timing.count").replace("{n}", String(d.answers)).replace("{r}", String(d.avg_rounds))}
            </p>
            <section>
              <h3 className="mb-1 font-medium">{t("salesAssistant.timing.causes")}</h3>
              {d.causes.length === 0 ? (
                <p className="text-muted-foreground">{t("salesAssistant.trace.nothingSlow")}</p>
              ) : (
                <ul data-testid="timing-causes" className="space-y-1">
                  {d.causes.map((c) => (
                    <li key={c.code} className="flex items-center gap-2">
                      <span className="min-w-0 flex-1">{c.text}</span>
                      <span className="num shrink-0 text-muted-foreground">
                        {t("salesAssistant.timing.inAnswers").replace("{n}", String(c.answers)).replace("{of}", String(d.answers))}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3 className="mb-1 font-medium">{t("salesAssistant.timing.slowest")}</h3>
              <ul data-testid="timing-slowest" className="space-y-2">
                {d.slowest.map((s, i) => (
                  <li key={i} className="rounded-xl border border-border px-3 py-2">
                    <div className="flex items-start gap-2">
                      <span className="min-w-0 flex-1 break-words">{s.question || "—"}</span>
                      <span className="num shrink-0 font-semibold">{seconds(s.total_ms)} {t("salesAssistant.trace.sec")}</span>
                    </div>
                    {s.reasons.length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-[11.5px] text-muted-foreground">
                        {s.reasons.map((r) => (
                          <li key={r}>• {r}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            {d.untraced > 0 && (
              <p className="text-[11px] text-muted-foreground">
                {t("salesAssistant.timing.untraced").replace("{n}", String(d.untraced))}
              </p>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
