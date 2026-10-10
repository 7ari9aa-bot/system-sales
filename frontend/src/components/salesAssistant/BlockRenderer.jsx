/** Render blocks for an assistant turn — the CLOSED server vocabulary.
 *  Money values arrive as strings and are formatted for DISPLAY only
 *  (digit grouping); they are never parsed into math. Unknown block types
 *  render as nothing — the contract refuses to invent a renderer. */

import React from "react";
import { AlertTriangle, Info } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";

const groupDigits = (value) => {
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value.trim())) return value;
  const [intPart, decPart] = value.trim().split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
};

function KpiRow({ block }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-surface px-3 py-2">
      <span className="text-[12.5px] text-muted-foreground">{block.label || block.metric}</span>
      <span className="font-display text-[14px] font-semibold whitespace-nowrap">
        {groupDigits(block.value)}
        {block.unit ? <span className="text-[11.5px] text-muted-foreground"> {block.unit}</span> : null}
      </span>
      {block.window ? <Badge tone="muted">{block.window}</Badge> : null}
    </div>
  );
}

export default function BlockRenderer({ blocks }) {
  const t = useT();
  if (!Array.isArray(blocks) || blocks.length === 0) return null;
  const kpis = blocks.filter((b) => b?.type === "kpi");
  const rest = blocks.filter((b) => b?.type !== "kpi");
  return (
    <div className="space-y-2 min-w-0">
      {kpis.length > 0 && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {kpis.map((b, i) => <KpiRow key={`kpi-${i}`} block={b} />)}
        </div>
      )}
      {rest.map((b, i) => {
        if (!b || typeof b !== "object") return null;
        switch (b.type) {
          case "text":
            return (
              <div key={`t-${i}`} className="text-[13.5px] leading-6 whitespace-pre-wrap break-words">
                {b.body}
              </div>
            );
          case "findings":
            return (
              <ul key={`f-${i}`} className="space-y-1.5">
                {b.items?.map((f, j) => (
                  <li key={j} className="flex items-start gap-2 text-[13px] leading-6">
                    <Badge tone={f.confidence === "HIGH" ? "success" : f.confidence === "MEDIUM" ? "primary" : "muted"}>
                      {f.confidence}
                    </Badge>
                    <span className="min-w-0 break-words">{f.statement}</span>
                  </li>
                ))}
              </ul>
            );
          case "notice":
            return (
              <div
                key={`n-${i}`}
                className={
                  b.severity === "warning"
                    ? "flex items-start gap-2 rounded-xl bg-warning/10 text-warning px-3 py-2 text-[12.5px]"
                    : "flex items-start gap-2 rounded-xl bg-surface text-muted-foreground px-3 py-2 text-[12.5px]"
                }
              >
                {b.severity === "warning" ? <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> : <Info className="h-4 w-4 shrink-0 mt-0.5" />}
                <span className="min-w-0 break-words">{b.message}</span>
              </div>
            );
          case "refs":
            return (
              <div key={`r-${i}`} className="flex flex-wrap items-center gap-1.5 pt-0.5">
                {b.analysis_id && <Badge tone="muted">{t("salesAssistant.refAnalysis")}</Badge>}
                {b.run_id && <Badge tone="muted">{t("salesAssistant.refRun")}</Badge>}
              </div>
            );
          default:
            return null; // unknown type — never invent a renderer
        }
      })}
    </div>
  );
}
