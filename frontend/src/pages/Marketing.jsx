import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Megaphone, Users, Zap } from "lucide-react";
import { PageHeader } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function Marketing() {
  const t = useT();
  const tabs = [
    { to: "/marketing", end: true, icon: Megaphone, label: t("marketing.tabs.campaigns") },
    { to: "/marketing/audience", icon: Users, label: t("marketing.tabs.audience") },
    { to: "/marketing/automation", icon: Zap, label: t("marketing.tabs.automation") },
  ];
  return (
    <div>
      <PageHeader title={t("marketing.title")} subtitle={t("marketing.subtitle")} />
      <div className="flex gap-1 mb-5 border-b border-border">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 px-3.5 py-2.5 text-[13px] font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
                  isActive ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
                )
              }
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </NavLink>
          );
        })}
      </div>
      <Outlet />
    </div>
  );
}