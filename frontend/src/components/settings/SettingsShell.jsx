import React from "react";
import { cn } from "@/lib/utils";

export default function SettingsShell({ title, subtitle, children, actions }) {
  return (
    <div className="w-full space-y-4 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[22px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-[13px] text-muted-foreground mt-1 max-w-xl">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

// A section, not a box: a heading, a hairline under it, and the content on the page itself.
// The bordered white card read as a panel floating on a panel; settings pages are long forms and
// lists, and they read better when the content simply sits on the page.
export function SettingCard({ title, desc, children, className }) {
  return (
    <section className={cn("min-w-0", className)}>
      {(title || desc) && (
        <div className="border-b border-border pb-2">
          {title && <h2 className="font-display text-[14px] font-semibold leading-5">{title}</h2>}
          {desc && <p className="text-[12.5px] text-muted-foreground mt-0.5">{desc}</p>}
        </div>
      )}
      <div className="pt-1.5">{children}</div>
    </section>
  );
}

export function SettingRow({ label, desc, children, last, stretch }) {
  return (
    <div className={cn("flex flex-col sm:flex-row sm:items-center sm:justify-between gap-x-6 gap-y-1 py-2.5", !last && "border-b border-border")}>
      <div className="min-w-0">
        <div className="text-[13px] font-medium leading-5">{label}</div>
        {desc && <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>}
      </div>
      <div className={cn(stretch ? "min-w-0 max-sm:w-full" : "shrink-0")}>{children}</div>
    </div>
  );
}
