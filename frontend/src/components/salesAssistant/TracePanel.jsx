/** "Thought for N s": the answer's measured steps, each opening to the model's own thinking, and
 *  why the answer took what it took. While the answer is written it is open and live; once done it
 *  folds into one line above the reply, like ChatGPT. All logic is in traceView.js. */
import React, { useEffect, useRef, useState } from "react";
import { Brain, Check, ChevronDown, Clock, Database, PenLine, X } from "lucide-react";
import { useT } from "@/lib/i18n";
import { canOpen, seconds, stepLabel, thinkingMs, traceSteps, traceSummary } from "./traceView";

/** Ticks while something is open, so a running step shows its seconds going up. */
function useNow(active) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

function StepIcon({ step }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  if (!step.done) return <span className="mx-[3px] h-2 w-2 shrink-0 rounded-full bg-primary animate-pulse" />;
  if (step.ok === false) return <X className={`${cls} text-destructive`} />;
  if (step.kind === "tool") return <Database className={`${cls} text-muted-foreground`} />;
  if (step.purpose === "rewrite" || step.purpose === "fill_gap") return <PenLine className={`${cls} text-amber-600`} />;
  return <Brain className={`${cls} text-primary/80`} />;
}

export default function TracePanel({ trace, live = false }) {
  const t = useT();
  const steps = traceSteps(trace);
  const summary = traceSummary(trace);
  const [open, setOpen] = useState(live);
  const [opened, setOpened] = useState(() => new Set());
  // when the page first saw each running step: the server's clock is not the browser's, so a
  // running step's seconds are counted from when it appeared here, and replaced by the measured
  // value as soon as the server writes it
  const firstSeen = useRef(new Map());
  const running = steps.some((s) => !s.done);
  const now = useNow(live && running);
  for (const s of steps) if (!s.done && !firstSeen.current.has(s.id)) firstSeen.current.set(s.id, Date.now());

  useEffect(() => {
    if (live) setOpen(true);
  }, [live]);

  if (steps.length === 0 && !summary) return null;

  const toggle = (id) =>
    setOpened((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const header = live
    ? t("salesAssistant.trace.thinkingNow")
    : t("salesAssistant.trace.thoughtFor").replace("{s}", seconds(thinkingMs(trace)));

  return (
    <div data-testid="assistant-trace" className="mb-2 text-[12.5px]">
      <button
        type="button"
        data-testid="assistant-trace-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg px-1.5 py-0.5 text-muted-foreground hover:bg-surface hover:text-foreground transition-colors"
      >
        <Clock className="h-3.5 w-3.5" />
        <span>{header}</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="mt-1.5 border-s-2 border-border ps-3 space-y-1">
          <ul data-testid="assistant-trace-steps" className="space-y-0.5">
            {steps.map((s) => {
              const ms = s.done ? s.ms : now - (firstSeen.current.get(s.id) ?? now);
              const expandable = canOpen(s);
              const isOpen = opened.has(s.id);
              return (
                <li key={s.id} data-testid="assistant-trace-step" data-kind={s.kind} data-done={s.done ? "true" : "false"}>
                  <button
                    type="button"
                    disabled={!expandable}
                    aria-expanded={expandable ? isOpen : undefined}
                    onClick={() => expandable && toggle(s.id)}
                    className={`flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-start ${
                      expandable ? "hover:bg-surface cursor-pointer" : "cursor-default"
                    } ${s.done ? "text-muted-foreground" : "text-foreground"}`}
                  >
                    <StepIcon step={s} />
                    <span className="min-w-0 flex-1 truncate">{stepLabel(s, steps, t)}</span>
                    <span className="num shrink-0 tabular-nums text-[11.5px] text-muted-foreground/80">
                      {seconds(ms)} {t("salesAssistant.trace.sec")}
                    </span>
                    {expandable && (
                      <ChevronDown className={`h-3 w-3 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                    )}
                  </button>
                  {expandable && isOpen && (
                    <div
                      data-testid="assistant-trace-reasoning"
                      dir="auto"
                      className="ms-6 mt-1 mb-1.5 max-h-64 overflow-y-auto scroll-slim whitespace-pre-wrap break-words rounded-lg bg-surface px-2.5 py-2 text-[11.5px] leading-5 text-muted-foreground"
                    >
                      {s.reasoning}
                      {s.reasoningCut ? <span className="block mt-1 italic">{t("salesAssistant.trace.cut")}</span> : null}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>

          {summary && (
            <div data-testid="assistant-trace-summary" className="pt-1.5 space-y-1">
              <p className="num text-[11.5px] text-muted-foreground">
                {t("salesAssistant.trace.split")
                  .replace("{total}", seconds(summary.total_ms))
                  .replace("{model}", seconds(summary.model_ms))
                  .replace("{tools}", seconds(summary.tools_ms))
                  .replace("{other}", seconds(summary.other_ms))}
              </p>
              {Array.isArray(summary.reasons) && summary.reasons.length > 0 ? (
                <div data-testid="assistant-trace-why">
                  <p className="text-[11.5px] font-medium text-foreground/80">{t("salesAssistant.trace.why")}</p>
                  <ul className="mt-0.5 space-y-0.5">
                    {summary.reasons.map((r) => (
                      <li key={r} className="flex gap-1.5 text-[11.5px] text-muted-foreground">
                        <span aria-hidden="true">•</span>
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                  <Check className="h-3 w-3 text-primary/70" />
                  {t("salesAssistant.trace.nothingSlow")}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
