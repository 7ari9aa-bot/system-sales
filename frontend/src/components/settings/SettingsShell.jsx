import React from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

export default function SettingsShell({ title, subtitle, children, actions }) {
  const { lang } = useI18n();
  return (
    <div className="space-y-5 animate-fade-in">
      <div className={cn("flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3", lang === "ar" && "sm:flex-row-reverse")}>
        <div className={cn("min-w-0", lang === "ar" && "text-right")}>
          <h1 className="font-display text-[22px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-[13px] text-muted-foreground mt-1 max-w-xl">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function SettingCard({ title, desc, children, className }) {
  return (
    <section className={cn("rounded-xl bg-card border border-border", className)}>
      {(title || desc) && (
        <div className="px-5 pt-4 pb-1">
          {title && <h2 className="font-display text-[15px] font-semibold">{title}</h2>}
          {desc && <p className="text-[12.5px] text-muted-foreground mt-0.5">{desc}</p>}
        </div>
      )}
      <div className="px-5 pb-4">{children}</div>
    </section>
  );
}

export function SettingRow({ label, desc, children, last }) {
  return (
    <div className={cn("flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 py-3.5", !last && "border-b border-border")}>
      <div className="min-w-0">
        <div className="text-[13.5px] font-medium">{label}</div>
        {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
