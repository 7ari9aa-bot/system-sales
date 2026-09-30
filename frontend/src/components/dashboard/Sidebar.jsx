import React, { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Inbox,
  Users,
  ShoppingBag,
  Package,
  Boxes,
  Megaphone,
  Sparkles,
  BarChart3,
  Gauge,
  ChevronDown,
} from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import Logo from "@/components/dashboard/Logo";
import useSalesStats from "@/hooks/useSalesStats";
import { apiCached } from "@/lib/api";

export default function Sidebar({ open, onClose, collapsed = false }) {
  const { pathname } = useLocation();
  const t = useT();

  // شارات حقيقية: غير المقروء من read model السيرفر، والمخزون من
  // النطاقين المنفصلين (منخفض + نافد) — بدل أرقام ثابتة.
  const live = useSalesStats("30d");
  const unread = live?.unread ?? 0;
  const stockIssues = (live?.lowStock ?? 0) + (live?.outOfStock ?? 0);

  // الحساب الحقيقي من /auth/me بدل اسم مكتوب يدويًا
  const [email, setEmail] = React.useState("");
  React.useEffect(() => {
    let alive = true;
    apiCached("/auth/me", { ttlMs: 60_000 })
      .then((me) => alive && setEmail(me?.email || ""))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const displayName = email ? email.split("@")[0].replace(/[._-]+/g, " ").trim() : "—";
  const initials = (email.slice(0, 2) || "·").toUpperCase();

  const NAV = [
    { section: t("nav.workspace"), items: [{ to: "/dashboard", label: t("nav.home"), icon: LayoutDashboard, end: true }] },
    {
      section: t("nav.engage"),
      items: [
        { to: "/inbox", label: t("nav.inbox"), icon: Inbox, badge: unread },
        { to: "/customers", label: t("nav.customers"), icon: Users },
      ],
    },
    {
      section: t("nav.sell"),
      items: [
        { to: "/orders", label: t("nav.orders"), icon: ShoppingBag },
        { to: "/products", label: t("nav.products"), icon: Package },
        { to: "/inventory", label: t("nav.inventory"), icon: Boxes, badge: stockIssues },
      ],
    },
    {
      section: t("nav.grow"),
      items: [
        { to: "/marketing", label: t("nav.marketing"), icon: Megaphone },
        { to: "/ai", label: t("nav.ai"), icon: Sparkles },
        { to: "/analytics", label: t("nav.analytics"), icon: BarChart3 },
        { to: "/usage", label: t("nav.usage"), icon: Gauge },
      ],
    },
  ];

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-foreground/20 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed z-40 inset-y-0 left-0 bg-sidebar border-r border-sidebar-border flex flex-col transition-all duration-300 lg:translate-x-0",
          open ? "translate-x-0 w-[248px]" : "-translate-x-full w-[248px]",
          collapsed ? "lg:translate-x-0 lg:w-[68px]" : "lg:w-[248px]"
        )}
      >
        {/* Brand */}
        <div className={cn("h-16 flex items-center border-b border-sidebar-border shrink-0", collapsed ? "justify-center px-2" : "gap-2.5 px-5")}>
          <Logo size={28} />
          {!collapsed && (
            <div className="leading-tight min-w-0">
              <div className="font-display font-bold text-[15px] tracking-wide text-foreground whitespace-nowrap truncate">{t("app.name")}</div>
              <div className="text-[11px] text-muted-foreground tracking-wide uppercase whitespace-nowrap truncate">{t("app.tagline")}</div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className={cn("flex-1 overflow-y-auto scrollbar-thin py-4 space-y-6", collapsed ? "px-2" : "px-3")}>
          {NAV.map((group) => (
            <div key={group.section} className={collapsed ? "space-y-1" : undefined}>
              {!collapsed && (
                <div className="px-3 mb-1.5 text-[10.5px] font-semibold tracking-[0.12em] uppercase text-muted-foreground whitespace-nowrap truncate text-center">
                  {group.section}
                </div>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = item.end ? pathname === item.to : pathname.startsWith(item.to);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      onClick={onClose}
                      title={collapsed ? item.label : undefined}
                      className={cn(
                        "group flex items-center rounded-lg text-[13.5px] font-medium transition-colors",
                        collapsed ? "relative justify-center px-0 py-2.5" : "gap-3 px-3 py-2",
                        active
                          ? "bg-primary/10 text-primary"
                          : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                      )}
                    >
                      <Icon className={cn("h-[17px] w-[17px] shrink-0", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                      {!collapsed && <span className="flex-1 min-w-0 truncate text-center">{item.label}</span>}
                      {!collapsed && item.badge ? (
                        <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md bg-primary text-primary-foreground tabular-nums">
                          {item.badge}
                        </span>
                      ) : null}
                      {collapsed && item.badge ? (
                        <span className="absolute top-0 right-0 h-1.5 w-1.5 rounded-full bg-primary" />
                      ) : null}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer — settings + profile merged into one account entry */}
        <div className="border-t border-sidebar-border p-3">
          <Link
            to="/settings"
            title={collapsed ? t("nav.settings") : undefined}
            className={cn(
              "flex items-center rounded-lg transition-colors",
              collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-3 py-2.5",
              pathname.startsWith("/settings")
                ? "bg-primary/10"
                : "hover:bg-sidebar-accent"
            )}
          >
            <div className="h-9 w-9 rounded-full bg-accent/15 text-accent grid place-items-center text-[12px] font-semibold shrink-0">
              {initials}
            </div>
            {!collapsed && (
              <div className="leading-tight flex-1 min-w-0 text-left">
                <div className={cn("text-[13px] font-medium whitespace-nowrap truncate", pathname.startsWith("/settings") ? "text-primary" : "text-foreground")} dir="ltr">{displayName}</div>
                <div className="text-[11px] text-muted-foreground whitespace-nowrap truncate">{t("sidebar.role")}</div>
              </div>
            )}
            {!collapsed && <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />}
          </Link>
        </div>
      </aside>
    </>
  );
}