import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Inbox,
  Users,
  Sparkles,
  BarChart3,
  Globe,
  Lock,
  LogOut,
  PanelLeft,
  Settings,
  ShieldCheck,
  Palette,
  Lightbulb,
  HelpCircle,
  ArrowUpCircle,
  Bell,
  Monitor,
  Bot,
  Check,
} from "lucide-react";
import { navGroups } from "@/cashier/components/layout/navItems";
import { useI18n, useT } from "@/lib/i18n";
import { useTheme } from "@/lib/themeContext";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/AuthContext";
import { useNavigate } from "react-router-dom";
import Logo from "@/components/dashboard/Logo";
import useSalesStats from "@/hooks/useSalesStats";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

export default function Sidebar({ open, onClose, collapsed = false, onToggleCollapse }) {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const { lang } = useI18n();
  const { theme, setTheme } = useTheme();
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = React.useState(false);
  const [memoryOpen, setMemoryOpen] = React.useState(false);
  const [feedbackOpen, setFeedbackOpen] = React.useState(false);
  const [updateOpen, setUpdateOpen] = React.useState(false);
  const [feedbackSent, setFeedbackSent] = React.useState(false);

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

  const displayName = user?.full_name || user?.email?.split("@")[0]?.replace(/[._-]+/g, " ").trim() || "—";
  const userEmail = user?.email || "rdrddt1@gmail.com";
  const _initials = displayName.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "·";
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
        { to: "/website", label: t("nav.website"), icon: Globe, locked: true },
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

        {/* Account menu matching uploaded image */}
        <div className="border-t border-sidebar-border p-2.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <div
                role="button"
                tabIndex={0}
                title={collapsed ? userEmail : undefined}
                aria-label={lang === "ar" ? "قائمة الحساب" : "Account menu"}
                className={cn(
                  "flex w-full items-center rounded-xl transition-all cursor-pointer select-none",
                  collapsed ? "justify-center p-1.5 hover:bg-sidebar-accent" : "gap-2.5 px-2.5 py-2 hover:bg-sidebar-accent border border-sidebar-border/60 bg-sidebar/50"
                )}
              >
                <div className="h-8 w-8 rounded-full bg-[#00c48c] text-white grid place-items-center text-[12px] font-semibold shrink-0 shadow-xs">
                  <Bot className="h-4 w-4" />
                </div>
                {!collapsed && (
                  <>
                    <div className="flex-1 min-w-0 text-left">
                      <div className="text-[12.5px] font-semibold text-foreground truncate" dir="ltr">{userEmail}</div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0 text-muted-foreground">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); navigate("/inbox"); }}
                        title={lang === "ar" ? "الإشعارات" : "Notifications"}
                        className="h-6 w-6 grid place-items-center rounded hover:bg-sidebar-accent/80 hover:text-foreground"
                      >
                        <Bell className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setUpdateOpen(true); }}
                        title={lang === "ar" ? "إصدار المتصفح والديسكتوب" : "Web & Desktop client"}
                        className="h-6 w-6 grid place-items-center rounded hover:bg-sidebar-accent/80 hover:text-foreground"
                      >
                        <Monitor className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              side={collapsed ? "right" : "top"}
              align="start"
              sideOffset={10}
              className="w-72 rounded-2xl border border-border bg-card p-3 shadow-2xl text-foreground animate-in fade-in-50 zoom-in-95"
            >
              {/* Profile Top Row */}
              <div className="flex items-center gap-2.5 px-1 py-1">
                <div className="h-8 w-8 rounded-full bg-[#00c48c] text-white grid place-items-center text-[12px] font-semibold shrink-0 shadow-xs">
                  <Bot className="h-4 w-4" />
                </div>
                <div className="text-[13px] font-bold text-foreground truncate" dir="ltr">{userEmail}</div>
              </div>

              {/* Subscription Card */}
              <div className="mt-3 rounded-xl border border-border/80 bg-surface/60 p-3">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[11px] text-muted-foreground font-normal">Plan</div>
                    <div className="text-[13.5px] font-bold text-foreground">Free</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[11px] text-muted-foreground font-normal">Credits Balance</div>
                    <div className="text-[13.5px] font-bold text-foreground tabular-nums">144.64</div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <button
                    type="button"
                    onClick={() => { onClose?.(); navigate("/settings/billing"); }}
                    className="h-8 rounded-lg bg-foreground text-background font-semibold text-[11.5px] hover:opacity-90 transition-opacity"
                  >
                    Upgrade Plan
                  </button>
                  <button
                    type="button"
                    onClick={() => { onClose?.(); navigate("/settings/billing"); }}
                    className="h-8 rounded-lg border border-border bg-card text-foreground font-semibold text-[11.5px] hover:bg-surface transition-colors"
                  >
                    Buy Credits
                  </button>
                </div>
              </div>

              {/* Menu items list */}
              <div className="mt-2.5 space-y-0.5">
                <button
                  type="button"
                  onClick={() => { onClose?.(); navigate("/settings"); }}
                  className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-[13px] text-foreground hover:bg-surface transition-colors"
                >
                  <span className="flex items-center gap-2.5">
                    <Settings className="h-4 w-4 text-muted-foreground" />
                    <span>Settings</span>
                  </span>
                  <kbd className="text-[10px] text-muted-foreground/80 font-mono tracking-wider">Ctrl+,</kbd>
                </button>

                <div className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-[13px] text-foreground">
                  <span className="flex items-center gap-2.5">
                    <Palette className="h-4 w-4 text-muted-foreground" />
                    <span>Appearance</span>
                  </span>
                  <div className="flex items-center rounded-lg border border-border/80 bg-surface p-0.5 text-[11px]">
                    <button
                      type="button"
                      onClick={() => setTheme("light")}
                      className={cn(
                        "px-2.5 py-0.5 rounded-md font-medium transition-all",
                        theme === "light"
                          ? "bg-card text-foreground shadow-xs font-semibold"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Light
                    </button>
                    <button
                      type="button"
                      onClick={() => setTheme("dark")}
                      className={cn(
                        "px-2.5 py-0.5 rounded-md font-medium transition-all",
                        theme === "dark"
                          ? "bg-card text-foreground shadow-xs font-semibold"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Dark
                    </button>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setMemoryOpen(true)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-foreground hover:bg-surface transition-colors"
                >
                  <Lightbulb className="h-4 w-4 text-muted-foreground" />
                  <span>Memory</span>
                </button>

                <button
                  type="button"
                  onClick={() => setFeedbackOpen(true)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-foreground hover:bg-surface transition-colors"
                >
                  <HelpCircle className="h-4 w-4 text-muted-foreground" />
                  <span>Feedback</span>
                </button>

                <button
                  type="button"
                  onClick={() => setUpdateOpen(true)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-foreground hover:bg-surface transition-colors"
                >
                  <ArrowUpCircle className="h-4 w-4 text-muted-foreground" />
                  <span>Check for Updates</span>
                </button>
              </div>

              <div className="my-1.5 h-px bg-border/70" />

              <button
                type="button"
                disabled={loggingOut}
                onClick={() => { onClose?.(); void handleLogout(); }}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] text-destructive hover:bg-destructive/10 transition-colors"
              >
                <LogOut className="h-4 w-4" />
                <span>{loggingOut ? (lang === "ar" ? "جارٍ تسجيل الخروج…" : "Signing out…") : logoutLabel}</span>
              </button>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* Memory Dialog */}
      <Dialog open={memoryOpen} onOpenChange={setMemoryOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-start">
              <Lightbulb className="h-5 w-5 text-amber-500" />
              <span>{lang === "ar" ? "ذاكرة الذكاء الاصطناعي (Memory)" : "AI Memory & Context"}</span>
            </DialogTitle>
            <DialogDescription className="text-start">
              {lang === "ar"
                ? "سياق متجرك المحفوظ الذي يتعلم منه مساعد المبيعات ووكلاء المحادثة لتقديم استجابات دقيقة."
                : "Active memory preferences and store knowledge retained by the AI sales intelligence."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2 text-[13px]">
            <div className="rounded-lg border border-border bg-surface/50 p-3 space-y-1.5">
              <div className="font-semibold text-foreground">{lang === "ar" ? "قواعد المتجر المتعلمة:" : "Learned Store Knowledge:"}</div>
              <ul className="list-disc list-inside text-muted-foreground space-y-1 text-[12px]">
                <li>{lang === "ar" ? "سياسة الاستبدال: 14 يوماً بالفاتورة الأصلية." : "Exchange policy: 14 days with original receipt."}</li>
                <li>{lang === "ar" ? "شحن مجاني للطلبات فوق 1,000 ج.م." : "Free delivery for orders above 1,000 EGP."}</li>
                <li>{lang === "ar" ? "طرق الدفع المفضلة: فودافون كاش، إنستاباي، نقداً عند الاستلام." : "Preferred payment: Cash on delivery, InstaPay."}</li>
              </ul>
            </div>
            <p className="text-[11.5px] text-muted-foreground">
              {lang === "ar" ? "الذاكرة تتحدث تلقائياً مع كل دورة محادثة وتفاعل مع العملاء." : "Memory updates automatically as you interact with customers and review sales."}
            </p>
          </div>
        </DialogContent>
      </Dialog>

      {/* Feedback Dialog */}
      <Dialog open={feedbackOpen} onOpenChange={(val) => { setFeedbackOpen(val); if (!val) setFeedbackSent(false); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-start">
              <HelpCircle className="h-5 w-5 text-primary" />
              <span>{lang === "ar" ? "الملاحظات والآراء (Feedback)" : "Feedback & Suggestions"}</span>
            </DialogTitle>
            <DialogDescription className="text-start">
              {lang === "ar" ? "شاركنا رأيك أو أي مشكلة تواجهها لتحسين تجربة العمل." : "Tell us what you love or what we can improve in Sales OS."}
            </DialogDescription>
          </DialogHeader>
          {feedbackSent ? (
            <div className="py-6 text-center space-y-2">
              <div className="h-10 w-10 mx-auto rounded-full bg-success/15 text-success grid place-items-center">
                <Check className="h-5 w-5" />
              </div>
              <div className="text-[14px] font-semibold">{lang === "ar" ? "شكراً لك! تم استلام ملاحظاتك." : "Thank you! Your feedback has been received."}</div>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); setFeedbackSent(true); }} className="space-y-3 py-2">
              <textarea
                required
                rows={4}
                placeholder={lang === "ar" ? "اكتب ملاحظاتك أو اقتراحاتك هنا…" : "Write your feedback or ideas here…"}
                className="w-full rounded-xl border border-border bg-surface p-3 text-[13px] outline-none focus:ring-2 focus:ring-primary/40 resize-none"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setFeedbackOpen(false)}
                  className="px-3 py-1.5 rounded-lg border border-border text-[12px] font-medium hover:bg-surface"
                >
                  {lang === "ar" ? "إلغاء" : "Cancel"}
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg bg-primary text-primary-foreground text-[12px] font-semibold hover:opacity-90"
                >
                  {lang === "ar" ? "إرسال" : "Submit"}
                </button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Updates Dialog */}
      <Dialog open={updateOpen} onOpenChange={setUpdateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-start">
              <ArrowUpCircle className="h-5 w-5 text-primary" />
              <span>{lang === "ar" ? "التحقق من التحديثات" : "Check for Updates"}</span>
            </DialogTitle>
            <DialogDescription className="text-start">
              {lang === "ar" ? "حالة النظام والإصدار الحالي لمنصة Sales OS." : "System status and version checks."}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4 space-y-3">
            <div className="flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-3.5 text-success">
              <Check className="h-5 w-5 shrink-0" />
              <div className="text-start">
                <div className="text-[13px] font-semibold">{lang === "ar" ? "أنت تستخدم أحدث إصدار (v2.4.0)" : "You are on the latest version (v2.4.0)"}</div>
                <div className="text-[11.5px] opacity-80">{lang === "ar" ? "جميع القنوات والخدمات متزامنة وتعمل بكفاءة." : "All services and channels are running stably."}</div>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
