import React, { useState } from "react";
import { Search, Plus, Crown, Loader2 } from "lucide-react";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { formatCurrency } from "@/lib/dashboardData";
import useCustomers from "@/hooks/useCustomers";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import CustomerDrawer from "@/components/customers/CustomerDrawer";

export default function Customers() {
  const t = useT();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(null);
  const customers = useCustomers();
  const filtered = (customers || []).filter((c) => c.name.toLowerCase().includes(q.toLowerCase()));

  const STATUS = {
    active: { label: t("customers.status.active"), tone: "primary" },
    lead: { label: t("customers.status.lead"), tone: "accent" },
    vip: { label: t("customers.status.vip"), tone: "warning" },
  };

  return (
    <div>
      <PageHeader
        title={t("customers.title")}
        subtitle={t("customers.subtitle")}
        actions={
          <>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t("customers.search")}
                className="h-9 w-56 pl-9 pr-3 rounded-lg bg-card border border-border text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/30"
              />
            </div>
            <button className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
              <Plus className="h-4 w-4" /> {t("customers.add")}
            </button>
          </>
        }
      />

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] table-fixed text-left">
            <colgroup>
              <col style={{ width: "26%" }} /><col style={{ width: "17%" }} /><col style={{ width: "11%" }} />
              <col style={{ width: "17%" }} /><col style={{ width: "15%" }} /><col style={{ width: "14%" }} />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-medium px-5 py-3">{t("customers.col.customer")}</th>
                <th className="font-medium px-5 py-3">{t("customers.col.channel")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("customers.col.orders")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("customers.col.ltv")}</th>
                <th className="font-medium px-5 py-3">{t("customers.col.status")}</th>
                <th className="font-medium px-5 py-3">{t("customers.col.lastSeen")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((c) => (
                <tr key={c.id} onClick={() => setSelected(c)} className="hover:bg-surface/50 transition-colors cursor-pointer">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className="h-9 w-9 rounded-full bg-accent/15 text-accent grid place-items-center text-[12px] font-semibold">
                        {c.name.split(" ").map((n) => n[0]).join("")}
                      </div>
                      <span className="text-[13.5px] font-medium">{c.name}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <ChannelIcon channel={c.channel} className="h-6 w-6" />
                      <span className="text-[12.5px] text-muted-foreground">{t(`channel.${c.channel}`)}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right text-[13.5px] font-medium tabular-nums">{c.orders}</td>
                  <td className="px-5 py-3 text-right text-[13.5px] font-semibold tabular-nums">{formatCurrency(c.spent)}</td>
                  <td className="px-5 py-3">
                    <Badge tone={STATUS[c.status].tone}>
                      {c.status === "vip" && <Crown className="h-3 w-3" />}
                      {STATUS[c.status].label}
                    </Badge>
                  </td>
                  <td className="px-5 py-3 text-[12.5px] text-muted-foreground">{c.lastSeen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {customers === null && (
          <div className="py-12 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
        )}
        {customers !== null && filtered.length === 0 && (
          <div className="py-12 text-center">
            <p className="text-[13.5px] text-muted-foreground">{q ? t("customers.empty", { q }) : t("customers.none")}</p>
          </div>
        )}
      </div>

      <CustomerDrawer customer={selected} onClose={() => setSelected(null)} />
    </div>
  );
}