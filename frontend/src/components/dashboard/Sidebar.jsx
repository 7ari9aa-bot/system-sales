import React from "react";
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
  Globe,
  ChevronDown,
  LogOut,
  PanelLeft,
  Settings2,
  ScanLine,
  Undo2,
  ArrowLeftRight,
  History,
  CirclePlus,
} from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/AuthContext";
import { useNavigate } from "react-router-dom";
import Logo from "@/components/dashboard/Logo";
import useSalesStats from "@/hooks/useSalesStats";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function Sidebar({ open, onClose, collapsed = false, onToggleCollapse }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const { lang } = useI18n();
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = React.useState(false);

  // شارات حقيقية: غير المقروء من read model السيرفر، والمخزون من
  // النطاقين المنفصلين (منخفض + نافد) — بدل أرقام ثابتة.
  const live = useSalesStats("30d");
  const unread = live?.unread ?? null;
  const stockIssues = live?.lowStock == null || live?.outOfStock == null
    ? null
    : live.lowStock + live.outOfStock;

  const displayName = user?.full_name || user?.email?.split("@")[0]?.replace(/[._-]+/g, " ").trim() || "—";
  const initials = displayName.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "·";
  const logoutLabel = lang === "ar" ? "تسجيل الخروج" : "Sign out";

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    onClose?.();
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLoggingOut(false);
    }
  }

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
        {
          to: "/orders",
          label: t("nav.orders"),
          icon: ShoppingBag,
          children: [
            { key: "new", label: t("nav.newSale"), icon: ScanLine },
            { key: "returns", label: t("nav.returns"), icon: Undo2 },
            { key: "exchanges", label: t("nav.exchanges"), icon: ArrowLeftRight },
            { key: "history", label: t("nav.salesHistory"), icon: History },
          ],
        },
        { to: "/products", label: t("nav.products"), icon: Package },
        { to: "/products/new", label: t("nav.addProduct"), icon: CirclePlus },
        { to: "/inventory", label: t("nav.inventory"), icon: Boxes, badge: stockIssues },
      ],
    },
    {
      section: t("nav.grow"),
      items: [
        { to: "/marketing", label: t("nav.marketing"), icon: Megaphone },
        { to: "/ai", label: t("nav.ai"), icon: Sparkles },
        { to: "/analytics", label: t("nav.analytics"), icon: BarChart3 },
        { to: "/website", label: t("nav.website"), icon: Globe },
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
        {/* Brand and desktop sidebar toggle */}
        <div className={cn("h-16 flex items-center border-b border-sidebar-border shrink-0", collapsed ? "justify-between px-5 lg:justify-start lg:gap-1 lg:px-1.5" : "gap-2.5 px-5")}>
          <div className={cn("flex items-center min-w-0", collapsed ? "gap-0 lg:gap-1" : "gap-2.5")}>
            <Logo size={collapsed ? 24 : 28} />
            <div className={cn("leading-tight min-w-0", collapsed && "lg:hidden")}>
              <div className="font-display font-bold text-[15px] tracking-wide text-foreground whitespace-nowrap truncate">{t("app.name")}</div>
              <div className="text-[11px] text-muted-foreground tracking-wide uppercase whitespace-nowrap truncate">{t("app.tagline")}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={onToggleCollapse}
            title={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            aria-label={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            className={cn("hidden lg:grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-sidebar-border hover:bg-sidebar-accent text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", collapsed ? "h-7 w-7" : "ml-auto")}
          >
            <PanelLeft className={cn("h-[18px] w-[18px] transition-transform", collapsed && "rotate-180")} />
          </button>
        </div>

        {/* Nav */}
        <nav className={cn("flex-1 overflow-y-auto scrollbar-thin py-4 space-y-6", collapsed ? "px-2" : "px-3")}>
          {NAV.map((group) => (
            <div key={group.section} className={collapsed ? "space-y-1" : undefined}>
              {!collapsed && (
                <div className="px-3 mb-1.5 text-[10.5px] font-semibold tracking-[0.06em] uppercase text-muted-foreground/80 whitespace-nowrap truncate text-start">
                  {group.section}
                </div>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = item.end ? pathname === item.to : pathname.startsWith(item.to);
                  const Icon = item.icon;
                  const section = new URLSearchParams(search).get("s");
                  return (
                    <React.Fragment key={item.to}>
                      <Link
                        to={item.to}
                        onClick={onClose}
                        title={collapsed ? item.label : undefined}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "group flex items-center rounded-lg text-[13.5px] font-medium transition-colors",
                          collapsed ? "relative justify-center px-0 py-2.5" : "gap-3 px-3 py-2",
                          active
                            ? "bg-primary/10 text-primary"
                            : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                        )}
                      >
                        <Icon className={cn("h-[17px] w-[17px] shrink-0", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                        {!collapsed && <span className="flex-1 min-w-0 truncate text-start">{item.label}</span>}
                        {!collapsed && item.badge ? (
                          <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md bg-pill text-pill-foreground tabular-nums">
                            {item.badge}
                          </span>
                        ) : null}
                        {collapsed && item.badge ? (
                          <span className="absolute top-0 right-0 h-1.5 w-1.5 rounded-full bg-primary" />
                        ) : null}
                      </Link>
                      {!collapsed && item.children && active ? (
                        <div className="ms-5 mt-0.5 mb-1 space-y-0.5 border-s border-sidebar-border ps-2">
                          {item.children.map((child) => {
                            const childActive = section === child.key;
                            const ChildIcon = child.icon;
                            return (
                              <Link
                                key={child.key}
                                to={`${item.to}?s=${child.key}`}
                                onClick={onClose}
                                className={cn(
                                  "group flex items-center gap-3 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
                                  childActive
                                    ? "bg-primary/10 font-semibold text-primary"
                                    : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                                )}
                              >
                                <ChildIcon className={cn("h-[17px] w-[17px] shrink-0", childActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                                <span className="flex-1 min-w-0 truncate text-start">{child.label}</span>
                              </Link>
                            );
                          })}
                        </div>
                      ) : null}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Compact account menu */}
        <div className="border-t border-sidebar-border p-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title={collapsed ? displayName : undefined}
                aria-label={lang === "ar" ? "قائمة الحساب" : "Account menu"}
                className={cn(
                  "flex w-full items-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-3 py-2.5",
                  pathname.startsWith("/settings") ? "bg-primary/10" : "hover:bg-sidebar-accent"
                )}
              >
                <div className="h-9 w-9 rounded-full bg-pill text-pill-foreground grid place-items-center text-[12px] font-semibold shrink-0">{initials}</div>
                {!collapsed && (
                  <div className="leading-tight flex-1 min-w-0 text-left">
                    <div className={cn("text-[13px] font-medium whitespace-nowrap truncate", pathname.startsWith("/settings") ? "text-primary" : "text-foreground")} dir="ltr">{displayName}</div>
                    <div className="text-[11px] text-muted-foreground whitespace-nowrap truncate">{t("sidebar.role")}</div>
                  </div>
                )}
                {!collapsed && <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="right" align="end" sideOffset={8} className="w-64 rounded-xl border border-border bg-popover p-1.5 shadow-lg">
              <DropdownMenuLabel className="px-2 py-2 font-normal">
                <div className="text-[13px] font-medium text-foreground truncate" dir="ltr">{displayName}</div>
                {user?.email && <div className="mt-0.5 text-[11px] text-muted-foreground truncate" dir="ltr">{user.email}</div>}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => { onClose?.(); navigate("/settings"); }} className="h-9 cursor-pointer text-[13px]">
                <Settings2 className="h-4 w-4" />
                <span>{t("nav.settings")}</span>
              </DropdownMenuItem>
              <DropdownMenuItem disabled={loggingOut} onSelect={() => { onClose?.(); void handleLogout(); }} className="h-9 cursor-pointer text-[13px] text-destructive focus:text-destructive">
                <LogOut className="h-4 w-4" />
                <span>{loggingOut ? (lang === "ar" ? "جارٍ تسجيل الخروج…" : "Signing out…") : logoutLabel}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
    </>
  );
}
