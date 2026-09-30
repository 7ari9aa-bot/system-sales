import React from "react";
import { Plus, Zap, MessageSquare, Clock, Repeat, ArrowRight } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";

const FLOWS = [
  { id: "f1", name: "Abandoned cart recovery", trigger: "Cart left 1h", triggerIcon: Clock, action: "WhatsApp reminder", status: "active", reached: 312, converted: 48 },
  { id: "f2", name: "New customer welcome", trigger: "First order", triggerIcon: Zap, action: "Thank-you + tips", status: "active", reached: 426, converted: 0 },
  { id: "f3", name: "VIP restock alert", trigger: "Low-stock product", triggerIcon: Repeat, action: "Notify VIP segment", status: "active", reached: 42, converted: 11 },
  { id: "f4", name: "Win-back (60d inactive)", trigger: "No order 60d", triggerIcon: Clock, action: "Discount code", status: "paused", reached: 126, converted: 9 },
];

export default function Automation() {
  const t = useT();
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-[13px] text-muted-foreground">{t("marketing.automation.subtitle")}</p>
        <button className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
          <Plus className="h-4 w-4" /> {t("marketing.automation.new")}
        </button>
      </div>

      <div className="space-y-3">
        {FLOWS.map((f) => {
          const TIcon = f.triggerIcon;
          return (
            <div key={f.id} className="rounded-2xl bg-card border border-border p-4 hover:shadow-sm transition-shadow">
              <div className="flex items-center gap-4">
                <span className="h-10 w-10 rounded-xl bg-accent/10 text-accent grid place-items-center shrink-0"><Zap className="h-5 w-5" /></span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-semibold">{f.name}</span>
                    <Badge tone={f.status === "active" ? "success" : "muted"}>{t(`marketing.automation.${f.status}`)}</Badge>
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 text-[12px] text-muted-foreground">
                    <span className="inline-flex items-center gap-1"><TIcon className="h-3.5 w-3.5" /> {f.trigger}</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                    <span className="inline-flex items-center gap-1"><MessageSquare className="h-3.5 w-3.5" /> {f.action}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[12.5px] text-muted-foreground">{t("marketing.automation.reached")}</div>
                  <div className="font-display text-[18px] font-semibold tabular-nums">{f.reached.toLocaleString()}</div>
                  {f.converted > 0 && <div className="text-[11.5px] text-success">{f.converted} {t("marketing.automation.converted")}</div>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}