import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Inbox,
  Users,
  Sparkles,
  BarChart3,
  Globe,
  LayoutTemplate,
  Lock,
  LogOut,
  PanelLeft,
  Settings,
  ShieldCheck,
  Camera,
  ChevronDown,
  Loader2,
} from "lucide-react";
import { navGroups } from "@/cashier/components/layout/navItems";
import { useI18n, useT } from "@/lib/i18n";
import { useTheme } from "@/lib/themeContext";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { avatarErrorKey, isAcceptedImage } from "@/lib/avatarUpload";
import { useAuth } from "@/lib/AuthContext";
import { useNavigate } from "react-router-dom";
import Logo from "@/components/dashboard/Logo";
import AccountAvatar from "@/components/dashboard/AccountAvatar";
import useSalesStats from "@/hooks/useSalesStats";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function Sidebar({ open, onClose, collapsed = false, onToggleCollapse }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const { lang, setLang } = useI18n();
  const { theme, setTheme } = useTheme();
  const { user, logout, refreshUser } = useAuth();
  const [loggingOut, setLoggingOut] = React.useState(false);
  const [avatarBusy, setAvatarBusy] = React.useState(false);
  const [avatarError, setAvatarError] = React.useState("");
  const [avatarNotice, setAvatarNotice] = React.useState("");
  const avatarInput = React.useRef(null);

  // Shortcut Ctrl+, to open Settings
  React.useEffect(() => {
    function handleKeyDown(event) {
      if ((event.ctrlKey || event.metaKey) && event.key === ",") {
        event.preventDefault();
        navigate("/settings");
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [navigate]);

  // شارات حقيقية: غير المقروء من read model السيرفر، والمخزون من النطاقين
  const live = useSalesStats();
  const unread = live?.unread ?? null;
  const stockIssues = live?.lowStock == null || live?.outOfStock == null
    ? null
    : live.lowStock + live.outOfStock;

  // «Website Dashboard» appears only once the tenant has an active website —
  // re-checked on every route change so it shows right after purchase.
  const [hasActiveSite, setHasActiveSite] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    api("/website/overview")
      .then((data) => { if (alive) setHasActiveSite(data?.state === "active"); })
      .catch(() => { if (alive) setHasActiveSite(false); });
    return () => { alive = false; };
  }, [pathname]);

  const displayName = user?.full_name?.trim() || user?.email || "—";
  const userEmail = user?.email || "—";

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

  async function uploadAvatar(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || avatarBusy) return;
    if (!isAcceptedImage(file)) {
      setAvatarError(t("avatar.notImage"));
      return;
    }
    setAvatarBusy(true);
    setAvatarError("");
    setAvatarNotice("");
    try {
      await api("/users/me/avatar", { method: "PUT", rawBody: file, contentType: file.type });
      await refreshUser();
      setAvatarNotice(t("avatar.saved"));
    } catch (error) {
      setAvatarError(t(avatarErrorKey(error)));
    } finally {
      setAvatarBusy(false);
    }
  }

  async function removeAvatar() {
    if (avatarBusy) return;
    setAvatarBusy(true);
    setAvatarError("");
    setAvatarNotice("");
    try {
      await api("/users/me/avatar", { method: "DELETE" });
      await refreshUser();
      setAvatarNotice(t("avatar.removed"));
    } catch (error) {
      setAvatarError(t(avatarErrorKey(error)));
    } finally {
      setAvatarBusy(false);
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
    ...navGroups.map((group) => ({
      section: t(group.titleKey, group.title),
      items: group.items.map((item) => ({
        to: `/cashier${item.to}`,
        label: item.label,
        icon: item.icon,
        badge: item.to === "/inventory" ? stockIssues : undefined,
      })),
    })),
    {
      section: t("nav.grow"),
      items: [
        { to: "/sales-assistant", label: "AI analysis", icon: Sparkles },
        { to: "/analytics", label: t("nav.analytics"), icon: BarChart3 },
        ...(user?.is_platform_admin
          ? [{ to: "/owner", label: t("nav.ownerConsole"), icon: ShieldCheck }]
          : []),
        { to: "/website", label: t("nav.website"), icon: Globe },
        ...(hasActiveSite
          ? [{ to: "/website/dashboard", label: t("nav.websiteDashboard"), icon: LayoutTemplate }]
          : []),
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
                  const active = item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(`${item.to}/`);
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
                        {!collapsed && item.locked ? (
                          <Lock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label={t("website.locked")} />
                        ) : null}
                        {collapsed && item.locked ? (
                          <Lock className="absolute top-1 right-1 h-2.5 w-2.5 text-muted-foreground" aria-hidden="true" />
                        ) : null}
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

        {/* Account menu — the controls this product really has. */}
        <div className="border-t border-sidebar-border p-2.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title={collapsed ? userEmail : undefined}
                aria-label={t("account.menu")}
                className={cn(
                  "flex w-full items-center rounded-xl transition-all cursor-pointer select-none",
                  collapsed ? "justify-center p-1.5 hover:bg-sidebar-accent" : "gap-2.5 px-2.5 py-2 hover:bg-sidebar-accent border border-sidebar-border/60 bg-sidebar/50"
                )}
              >
                <AccountAvatar user={user} />
                {!collapsed && (
                  <>
                    <div className="flex-1 min-w-0 text-left">
                      <div className="text-[12.5px] font-semibold text-foreground truncate" dir="ltr">{userEmail}</div>
                    </div>
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  </>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side={collapsed ? "right" : "top"}
              align="start"
              sideOffset={10}
              className="w-72 rounded-2xl border border-border bg-card p-3 shadow-2xl text-foreground animate-in fade-in-50 zoom-in-95"
            >
              {/* Identity — the account's own values, never a placeholder */}
              <div className="flex items-center gap-2.5 px-1 py-1">
                <AccountAvatar user={user} size="md" />
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-foreground truncate" dir="auto">{displayName}</div>
                  <div className="text-[11.5px] text-muted-foreground truncate" dir="ltr">{userEmail}</div>
                </div>
              </div>

              {/* Profile picture — an action, so it is a menu item */}
              <DropdownMenuSeparator className="my-2" />
              <DropdownMenuItem
                disabled={avatarBusy}
                onSelect={(event) => { event.preventDefault(); avatarInput.current?.click(); }}
                className="gap-2.5 text-[13px]"
              >
                {avatarBusy
                  ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
                  : <Camera className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}
                <span>{t(user?.avatar_url ? "account.avatar.change" : "account.avatar.add")}</span>
              </DropdownMenuItem>
              {user?.avatar_url && (
                <DropdownMenuItem
                  disabled={avatarBusy}
                  onSelect={(event) => { event.preventDefault(); void removeAvatar(); }}
                  className="gap-2.5 text-[13px]"
                >
                  <span className="h-4 w-4" aria-hidden="true" />
                  <span>{t("account.avatar.remove")}</span>
                </DropdownMenuItem>
              )}
              <input
                ref={avatarInput}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                aria-label={t("account.avatar.pick")}
                className="sr-only"
                onChange={uploadAvatar}
              />
              {avatarError && <p role="alert" className="mt-1.5 px-2 text-[11.5px] text-destructive">{avatarError}</p>}
              {avatarNotice && <p role="status" className="mt-1.5 px-2 text-[11.5px] text-muted-foreground">{avatarNotice}</p>}

              <DropdownMenuSeparator className="my-1.5" />

              <DropdownMenuItem onSelect={() => { onClose?.(); navigate("/settings"); }} className="gap-2.5 text-[13px]">
                <Settings className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <span>{t("nav.settings")}</span>
                <kbd className="ms-auto text-[10px] text-muted-foreground/80 font-mono tracking-wider">Ctrl+,</kbd>
              </DropdownMenuItem>

              {/* Theme and language are choices, so they are radio groups */}
              <div className="mt-1.5 px-2 pb-0.5 text-[11px] text-muted-foreground">{t("appearance.theme")}</div>
              <DropdownMenuRadioGroup value={theme} onValueChange={setTheme} aria-label={t("appearance.theme")}>
                {["system", "light", "dark"].map((option) => (
                  <DropdownMenuRadioItem
                    key={option}
                    value={option}
                    onSelect={(event) => event.preventDefault()}
                    className="py-1 text-[12.5px]"
                  >
                    {t(`appearance.theme.${option}`)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>

              <div className="mt-1.5 px-2 pb-0.5 text-[11px] text-muted-foreground">{t("appearance.language")}</div>
              <DropdownMenuRadioGroup value={lang} onValueChange={setLang} aria-label={t("appearance.language")}>
                {["ar", "en"].map((option) => (
                  <DropdownMenuRadioItem
                    key={option}
                    value={option}
                    onSelect={(event) => event.preventDefault()}
                    className="py-1 text-[12.5px]"
                  >
                    {t(`appearance.language.${option}`)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>

              <DropdownMenuSeparator className="my-1.5" />

              <DropdownMenuItem
                disabled={loggingOut}
                onSelect={() => { onClose?.(); void handleLogout(); }}
                className="gap-2.5 text-[13px] text-destructive focus:bg-destructive/10 focus:text-destructive"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                <span>{t(loggingOut ? "account.signingOut" : "account.signOut")}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
    </>
  );
}
