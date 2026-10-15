/** Render blocks for an assistant turn — the CLOSED server vocabulary.
 *  Each block type gets the same visual treatment as the dashboard's own
 *  stat cards (font-display tabular-nums, tone tiles) — the chat must read
 *  as the product, not a terminal. Money arrives as strings and is grouped
 *  for DISPLAY only; never parsed into math. Unknown types render nothing. */

import React from "react";
import {
  AlertTriangle,
  Banknote,
  Info,
  Package,
  RotateCcw,
  ShoppingBag,
  Sparkles,
  TrendingUp,
  Truck,
  Users,
} from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";

const METRIC_ICONS = [
  ["revenue", Banknote],
  ["sales", TrendingUp],
  ["orders", ShoppingBag],
  ["aov", Banknote],
  ["refund", RotateCcw],
  ["returns", RotateCcw],
  ["customer", Users],
  ["shipping", Truck],
  ["fulfillment", Truck],
  ["stock", Package],
  ["inventory", Package],
];

const groupDigits = (value) => {
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value.trim())) return value;
  const [intPart, decPart] = value.trim().split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
};

function metricIcon(metric) {
  const needle = (metric || "").toLowerCase();
  for (const [frag, Icon] of METRIC_ICONS) {
    if (needle.includes(frag)) return Icon;
  }
  return Sparkles;
}

function KpiCard({ block }) {
  const Icon = metricIcon(block.metric);
  return (
    <div className="rounded-2xl bg-card border border-border p-3.5 hover:border-primary/30 transition-colors">
      <div className="flex items-center justify-between gap-2">
        <span className="h-8 w-8 rounded-lg grid place-items-center bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        {block.window ? <Badge tone="muted">{block.window}</Badge> : null}
      </div>
      <div className="mt-2.5 font-display text-[20px] font-semibold tabular-nums leading-none">
        {groupDigits(block.value)}
        {block.unit ? (
          <span className="text-[12px] font-medium text-muted-foreground"> {block.unit}</span>
        ) : null}
      </div>
      <div className="mt-1.5 text-[11.5px] text-muted-foreground leading-tight truncate">
        {block.label || block.metric}
      </div>
    </div>
  );
}

const CONFIDENCE_TONE = { HIGH: "success", MEDIUM: "primary", LOW: "muted" };

function FindingsCard({ items }) {
  const t = useT();
  return (
    <div className="rounded-2xl border border-border overflow-hidden">
      <div className="px-3.5 py-2 bg-surface text-[11.5px] font-medium text-muted-foreground">
        {t("salesAssistant.findingsTitle")}
      </div>
      <ul className="divide-y divide-border">
        {(items ?? []).map((f, j) => (
          <li key={j} className="px-3.5 py-2.5 flex items-start gap-2.5">
            <span
              className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                f.confidence === "HIGH"
                  ? "bg-success"
                  : f.confidence === "MEDIUM"
                    ? "bg-primary"
                    : "bg-muted-foreground/50"
              }`}
            />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] leading-6 break-words">{f.statement}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge tone={CONFIDENCE_TONE[f.confidence] || "muted"}>
                  {t("salesAssistant.confidence")}: {f.confidence}
                </Badge>
                {(f.evidence_refs ?? []).slice(0, 4).map((ref) => (
                  <span
                    key={ref}
                    className="rounded-md bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground"
                  >
                    {ref}
                  </span>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BlockRenderer({ blocks }) {
  const t = useT();
  if (!Array.isArray(blocks) || blocks.length === 0) return null;
  const kpis = blocks.filter((b) => b?.type === "kpi");
  const findings = blocks.filter((b) => b?.type === "findings");
  const rest = blocks.filter((b) => !["kpi", "findings"].includes(b?.type));

  return (
    <div className="space-y-2.5 min-w-0">
      {kpis.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {kpis.map((b, i) => <KpiCard key={`kpi-${i}`} block={b} />)}
        </div>
      )}
      {rest.map((b, i) => {
        if (!b || typeof b !== "object") return null;
        switch (b.type) {
          case "text":
            return (
              <div
                key={`t-${i}`}
                className="text-[13.5px] leading-7 [&_strong]:font-semibold [&_code]:rounded-md [&_code]:bg-surface [&_code]:px-1 [&_code]:text-[12px] [&_ul]:list-disc [&_ul]:ps-5 [&_ol]:list-decimal [&_ol]:ps-5"
              >
                {b.body}
              </div>
            );
          case "findings":
            return <FindingsCard key={`f-${i}`} items={b.items} />;
          case "notice":
            return (
              <div
                key={`n-${i}`}
                className={
                  b.severity === "warning"
                    ? "flex items-start gap-2 rounded-2xl bg-warning/10 text-warning px-3.5 py-2.5 text-[12.5px] leading-6"
                    : "flex items-start gap-2 rounded-2xl bg-surface text-muted-foreground px-3.5 py-2.5 text-[12.5px] leading-6"
                }
              >
                {b.severity === "warning" ? (
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                ) : (
                  <Info className="h-4 w-4 shrink-0 mt-0.5" />
                )}
                <span className="min-w-0 break-words">{b.message}</span>
              </div>
            );
          case "refs":
            return (
              <div key={`r-${i}`} className="flex flex-wrap items-center gap-1.5">
                {b.analysis_id && (
                  <span className="inline-flex items-center gap-1 rounded-lg bg-primary-soft px-2 py-1 text-[11px] font-medium text-primary">
                    <Sparkles className="h-3 w-3" />
                    {t("salesAssistant.refAnalysis")}
                  </span>
                )}
                {b.run_id && (
                  <span className="inline-flex items-center gap-1 rounded-lg bg-surface px-2 py-1 text-[11px] font-medium text-muted-foreground">
                    {t("salesAssistant.refRun")}
                  </span>
                )}
              </div>
            );
          default:
            return null; // unknown type — never invent a renderer
        }
      })}
      {findings.map((b, i) => <FindingsCard key={`f-wrap-${i}`} items={b.items} />)}
    </div>
  );
}
