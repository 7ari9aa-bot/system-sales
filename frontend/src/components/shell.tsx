"use client";

import * as React from "react";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutDashboard,
  MessagesSquare,
  ListChecks,
  ClipboardList,
  Bell,
  Users,
  ShoppingCart,
  Package,
  Warehouse,
  Megaphone,
  Sparkles,
  Settings,
  Search,
  Plus,
  ChevronDown,
  ChevronsLeftRight,
  Menu,
  LogOut,
  Building2,
  Sun,
  Moon,
  Languages,
} from "lucide-react";
import { API_BASE_URL, API_PREFIX, getTokens, setTokens } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { getLang, getTheme, applyTheme, toggleTheme, setLang, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CommandPalette } from "@/components/command-palette";
import { NotificationsBell } from "@/components/notifications-bell";
import { HealthIndicator } from "@/components/health-indicator";
import { useMe } from "@/lib/queries";

/* ------------------------------------------------------------- nav model */

type NavItem = { href: string; label: string; icon: React.ReactNode; testid: string };
type NavGroup = { id: string; label: string; items: NavItem[] };

/* Built at render time (not module scope) so the labels follow the active
   language without a page reload. */
function buildNavGroups(): NavGroup[] {
  return [
    {
      id: "home",
      label: t.groupHome,
      items: [{ href: "/dashboard", label: t.dashboard, icon: <LayoutDashboard aria-hidden="true" />, testid: "nav-dashboard" }],
    },
    {
      id: "work",
      label: t.groupWork,
      items: [
        { href: "/my-work", label: t.myWork, icon: <ClipboardList aria-hidden="true" />, testid: "nav-my-work" },
        { href: "/notifications", label: t.notifications, icon: <Bell aria-hidden="true" />, testid: "nav-notifications" },
        { href: "/inbox", label: t.inbox, icon: <MessagesSquare aria-hidden="true" />, testid: "nav-inbox" },
        { href: "/tasks", label: t.myTasks, icon: <ListChecks aria-hidden="true" />, testid: "nav-tasks" },
      ],
    },
    {
      id: "business",
      label: t.groupBusiness,
      items: [
        { href: "/customers", label: t.customers, icon: <Users aria-hidden="true" />, testid: "nav-customers" },
        { href: "/orders", label: t.orders, icon: <ShoppingCart aria-hidden="true" />, testid: "nav-orders" },
        { href: "/products", label: t.products, icon: <Package aria-hidden="true" />, testid: "nav-products" },
        { href: "/inventory", label: t.inventory, icon: <Warehouse aria-hidden="true" />, testid: "nav-inventory" },
      ],
    },
    {
      id: "growth",
      label: t.groupGrowth,
      items: [{ href: "/marketing", label: t.marketing, icon: <Megaphone aria-hidden="true" />, testid: "nav-marketing" }],
    },
    {
      id: "ai",
      label: t.groupAi,
      items: [{ href: "/ai", label: t.ai, icon: <Sparkles aria-hidden="true" />, testid: "nav-ai" }],
    },
    {
      id: "admin",
      label: t.groupAdmin,
      items: [{ href: "/settings", label: t.settings, icon: <Settings aria-hidden="true" />, testid: "nav-settings" }],
    },
  ];
}

function buildCreateItems(): NavItem[] {
  return [
    { href: "/orders?new=1", label: t.newOrder, icon: <ShoppingCart aria-hidden="true" />, testid: "create-order" },
    { href: "/products?new=1", label: t.newProduct, icon: <Package aria-hidden="true" />, testid: "create-product" },
    { href: "/marketing?new=1", label: t.newCampaign, icon: <Megaphone aria-hidden="true" />, testid: "create-campaign" },
    { href: "/ai?new=1", label: t.newKnowledge, icon: <Sparkles aria-hidden="true" />, testid: "create-knowledge" },
    { href: "/settings?new=1", label: t.newInvitation, icon: <Users aria-hidden="true" />, testid: "create-invitation" },
  ];
}

/* ------------------------------------------------------------- sidebar nav */

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState<Record<string, boolean>>({});
  const groups = buildNavGroups();

  return (
    <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 pb-4" aria-label="التنقل الرئيسي">
      {groups.map((group) => {
        const isCollapsed = collapsed[group.id] ?? false;
        return (
          <div key={group.id}>
            <button
              type="button"
              onClick={() => setCollapsed((c) => ({ ...c, [group.id]: !isCollapsed }))}
              aria-expanded={!isCollapsed}
              className="flex w-full items-center justify-between rounded-lg px-3 pb-1 pt-3 text-[11px] font-bold uppercase tracking-wide text-muted-foreground/80 transition-colors duration-150 hover:text-foreground"
            >
              <span>{group.label}</span>
              <ChevronDown
                aria-hidden="true"
                className={cn("size-3.5 transition-transform duration-200 ease-smooth", isCollapsed && "-rotate-90 rtl:rotate-90")}
              />
            </button>
            {!isCollapsed && (
              <ul className="mt-1 flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.href || pathname.startsWith(item.href + "/");
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        data-testid={item.testid}
                        className={cn(
                          "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-semibold transition-all duration-150 ease-smooth",
                          active
                            ? "bg-primary-soft text-primary"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        <span className="[&_svg]:size-4">{item.icon}</span>
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/* ------------------------------------------------------------- shell */

export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const me = useMe();
  const queryClient = useQueryClient();
  const email = me.data?.email ?? "";

  // حماية: بدون توكنات → صفحة الدخول
  React.useEffect(() => {
    if (!getTokens()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router, pathname]);

  // Cmd+K / Ctrl+K
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const [lang, setLangState] = useState<Lang>("ar");
  const createItems = buildCreateItems();

  useEffect(() => {
    applyTheme(getTheme());
    const saved = getLang();
    setLangState(saved);
    document.documentElement.lang = saved;
  }, []);

  function toggleLang() {
    const next: Lang = lang === "ar" ? "en" : "ar";
    setLang(next);
    // strings re-render in place; direction never flips
    setLangState(next);
    document.documentElement.lang = next;
  }

  function logout() {
    // أبلغ السيرفر أولًا (fire-and-forget) قبل مسح التوكنات محليًا
    const tokens = getTokens();
    if (tokens?.refresh_token) {
      void fetch(`${API_BASE_URL}${API_PREFIX}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      }).catch(() => {
        /* الشبكة غير متاحة — نتجاهل ونكمل الخروج */
      });
    }
    setTokens(null);
    queryClient.clear(); // منع وميض بيانات الحساب السابق عند الدخول التالي
    router.replace("/login");
  }

  function goCreate(href: string) {
    router.push(href);
  }

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-lg font-bold text-white">ف</span>
          <p className="text-[13px] text-muted-foreground">{t.loading}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-row-reverse bg-background">
      {/* Sidebar — RTL: على اليمين (أول عنصر في flex باتجاه rtl) */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-e border-border bg-card lg:flex">
        <SidebarNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar (§89) */}
        <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-card/85 px-4 backdrop-blur-md">
          {/* mobile menu */}
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="فتح القائمة"
            data-testid="open-sidebar"
          >
            <Menu aria-hidden="true" />
          </Button>

          {/* brand */}
          <Link href="/dashboard" className="flex items-center gap-2" aria-label={t.brand}>
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-sm font-bold text-white">ف</span>
            <span className="hidden text-[15px] font-bold sm:inline">{t.brand}</span>
          </Link>

          {/* workspace switcher (placeholder) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="ms-1 gap-1.5 text-muted-foreground" data-testid="workspace-switcher">
                <Building2 aria-hidden="true" className="size-4" />
                <span className="hidden max-w-32 truncate sm:inline">{t.workspace}</span>
                <ChevronDown aria-hidden="true" className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>{t.switchWorkspace}</DropdownMenuLabel>
              <DropdownMenuItem>
                <Building2 aria-hidden="true" />
                <span className="flex-1">{t.workspace}</span>
                <Badge variant="primary" className="ms-2">الحالي</Badge>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled>
                <Plus aria-hidden="true" />
                {t.addWorkspace}
                <Badge variant="outline" className="ms-2">قريبًا</Badge>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex-1" />

          {/* search / Cmd+K trigger */}
          <Button
            variant="secondary"
            size="sm"
            className="gap-2 text-muted-foreground"
            onClick={() => setPaletteOpen(true)}
            data-testid="open-command-palette"
          >
            <Search aria-hidden="true" className="size-4" />
            <span className="hidden sm:inline">{t.search}</span>
            <kbd className="hidden rounded-md border border-border border-b-2 bg-card px-1.5 py-0.5 text-[10.5px] font-bold sm:inline" dir="ltr">
              ⌘K
            </kbd>
          </Button>

          {/* + Create menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" className="gap-1.5" data-testid="create-menu">
                <Plus aria-hidden="true" className="size-4" />
                <span className="hidden sm:inline">{t.create}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{t.quickActions}</DropdownMenuLabel>
              {createItems.map((item) => (
                <DropdownMenuItem key={item.href} onSelect={() => goCreate(item.href)} data-testid={item.testid}>
                  {item.icon}
                  {item.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* notifications bell */}
          <NotificationsBell />

          {/* system health indicator (§103) */}
          <HealthIndicator />

          {/* theme toggle */}
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => toggleTheme()}
            aria-label="تبديل المظهر"
            data-testid="theme-toggle"
          >
            <Sun aria-hidden="true" className="hidden dark:block" />
            <Moon aria-hidden="true" className="block dark:hidden" />
          </Button>

          {/* language toggle — strings only, layout never flips */}
          <Button
            variant="ghost"
            size="sm"
            className="px-2 font-bold"
            onClick={() => toggleLang()}
            aria-label="Switch language"
            data-testid="lang-toggle"
          >
            {lang === "ar" ? "EN" : "ع"}
          </Button>

          {/* user menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="ms-1 flex size-8 items-center justify-center rounded-full bg-primary-soft text-[13px] font-bold text-primary transition-all duration-150 ease-smooth hover:ring-2 hover:ring-ring/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                aria-label="قائمة المستخدم"
                data-testid="user-menu"
              >
                {(email ? email[0] : "؟").toUpperCase()}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
              <DropdownMenuLabel className="max-w-52 truncate" dir="ltr">
                {email || "…"}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => goCreate("/settings")}>
                <Settings aria-hidden="true" />
                {t.settings}
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={logout} data-testid="logout">
                <LogOut aria-hidden="true" />
                {t.logout}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* main content — keyed by language so the page subtree re-renders in place */}
        <main key={lang} className="min-w-0 flex-1 p-4 sm:p-6">{children}</main>
      </div>

      {/* mobile sidebar */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="start" className="w-64 p-0 pt-4">
          <SheetTitle className="px-4 pb-2 text-start">
            <span className="flex items-center gap-2">
              <ChevronsLeftRight aria-hidden="true" className="size-4 text-muted-foreground" />
              {t.brand}
            </span>
          </SheetTitle>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
