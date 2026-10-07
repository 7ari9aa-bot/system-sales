import React, { useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeft, LogOut, User, MessageSquare, Wallet, Users, ShieldCheck, AlertTriangle, Menu, X, ChevronDown, Settings2,
} from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/AuthContext";
import Logo from "@/components/dashboard/Logo";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// Settings is an exceptional full-screen workspace: the dashboard shell is
// replaced by this dedicated sidebar + content area.
const NAV = [
  { to: "/settings", icon: User, labelKey: "settings.nav.profile", end: true },
  { to: "/settings/channels", icon: MessageSquare, labelKey: "settings.nav.channels" },
  { to: "/settings/billing", icon: Wallet, labelKey: "settings.nav.billing" },
  { to: "/settings/members", icon: Users, labelKey: "settings.nav.members" },
  { to: "/settings/security", icon: ShieldCheck, labelKey: "settings.nav.security" },
  { to: "/settings/danger", icon: AlertTriangle, labelKey: "settings.nav.danger" },
];

export default function SettingsLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const { lang } = useI18n();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const displayName = user?.full_name || user?.email?.split("@")[0] || "—";
  const initials = displayName
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "·";
  const logoutLabel = lang === "ar" ? "تسجيل الخروج" : "Sign out";

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <div data-dashboard-theme-scope className="min-h-screen bg-background">
      {open && (
        <div className="fixed inset-0 z-30 bg-foreground/20 backdrop-blur-sm lg:hidden" onClick={() => setOpen(false)} />
      )}

      <aside
        className={cn(
          "fixed z-40 inset-y-0 left-0 w-[264px] bg-sidebar border-r border-sidebar-border flex flex-col transition-transform duration-300",
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-sidebar-border">
          <Logo size={32} />
          <div className="leading-tight min-w-0">
            <div className="font-display font-bold text-[15px] tracking-wide text-foreground whitespace-nowrap truncate">{t("app.name")}</div>
            <div className="text-[11px] text-muted-foreground tracking-wide uppercase whitespace-nowrap truncate">{t("settings.title")}</div>
          </div>
          <button
            className="ml-auto lg:hidden h-8 w-8 grid place-items-center rounded-lg hover:bg-sidebar-accent text-muted-foreground"
            onClick={() => setOpen(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto scrollbar-thin px-3 py-4 space-y-0.5">
          {NAV.map((item) => {
            const active = item.end ? pathname === item.to : pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className={cn(
                  "group flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                )}
              >
                <Icon className={cn("h-[17px] w-[17px] shrink-0", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                <span className="flex-1 min-w-0 truncate">{t(item.labelKey)}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <Link
            to="/dashboard"
            onClick={() => setOpen(false)}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-[13.5px] font-medium text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
          >
            <ArrowLeft className="h-[17px] w-[17px] shrink-0 text-muted-foreground" />
            <span className="flex-1 min-w-0 truncate">{t("settings.backToApp")}</span>
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" aria-label={lang === "ar" ? "قائمة الحساب" : "Account menu"} className="mt-2 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <div className="h-8 w-8 rounded-full bg-accent/15 text-accent grid place-items-center text-[12px] font-semibold shrink-0">{initials}</div>
                <div className="leading-tight flex-1 min-w-0">
                  <div className="text-[12.5px] font-medium text-foreground whitespace-nowrap truncate" dir="ltr">{displayName}</div>
                  <div className="text-[11px] text-muted-foreground whitespace-nowrap truncate">{t("sidebar.role")}</div>
                </div>
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="right" align="end" sideOffset={8} className="w-64 rounded-xl border border-border bg-popover p-1.5 shadow-lg">
              <DropdownMenuLabel className="px-2 py-2 font-normal">
                <div className="text-[13px] font-medium text-foreground truncate" dir="ltr">{displayName}</div>
                {user?.email && <div className="mt-0.5 text-[11px] text-muted-foreground truncate" dir="ltr">{user.email}</div>}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => { setOpen(false); navigate("/settings"); }} className="h-9 cursor-pointer text-[13px]">
                <Settings2 className="h-4 w-4" />
                <span>{t("nav.settings")}</span>
              </DropdownMenuItem>
              <DropdownMenuItem disabled={loggingOut} onSelect={() => { setOpen(false); void handleLogout(); }} className="h-9 cursor-pointer text-[13px] text-destructive focus:text-destructive">
                <LogOut className="h-4 w-4" />
                <span>{loggingOut ? (lang === "ar" ? "جارٍ تسجيل الخروج…" : "Signing out…") : logoutLabel}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      <div className="lg:pl-[264px] min-w-0">
        <header className="sticky top-0 z-20 h-16 bg-background/80 backdrop-blur-md border-b border-border flex items-center gap-3 px-4 sm:px-6">
          <button
            className="lg:hidden h-9 w-9 grid place-items-center rounded-lg border border-border hover:bg-surface text-muted-foreground"
            onClick={() => setOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <h1 className={cn("font-display text-[16px] font-semibold whitespace-nowrap truncate", lang === "ar" && "ml-auto text-right")}>{t("settings.title")}</h1>
        </header>
        <main className="px-4 sm:px-6 lg:px-8 py-6 max-w-[1080px] mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
