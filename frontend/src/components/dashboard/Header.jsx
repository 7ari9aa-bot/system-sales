import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Bell, CircleHelp, Menu, ChevronDown, Check, Sun, Moon, Languages, BookOpen, LifeBuoy, Keyboard, Settings2, PanelLeft } from "lucide-react";
import { useDashboard } from "@/lib/dashboardContext";
import { DATE_RANGES } from "@/lib/dashboardData";
import { useT, useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/themeContext";
import { cn } from "@/lib/utils";
import TokenIndicator from "@/components/dashboard/TokenIndicator";
import GlobalSearch from "@/components/dashboard/GlobalSearch";

function Dropdown({ trigger, children, align = "left", width = "w-52" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((v) => !v)} className="outline-none">
        {trigger(open)}
      </button>
      {open && (
        <div
          className={cn(
            "absolute z-50 mt-2 rounded-xl border border-border bg-popover shadow-lg p-1.5 animate-fade-in",
            width,
            align === "right" ? "right-0" : "left-0"
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

const NOTIFICATIONS = [
  { id: "approval", to: "/ai", tone: "primary" },
  { id: "order", to: "/orders", tone: "success" },
  { id: "stock", to: "/inventory", tone: "warning" },
  { id: "message", to: "/inbox", tone: "primary" },
];

const HELP_ITEMS = [
  { id: "docs", to: "/settings", icon: BookOpen },
  { id: "shortcuts", to: "/settings", icon: Keyboard },
  { id: "support", to: "/settings/security", icon: LifeBuoy },
  { id: "settings", to: "/settings", icon: Settings2 },
];

function greeting(t) {
  const h = new Date().getHours();
  if (h < 12) return t("header.greeting.morning");
  if (h < 18) return t("header.greeting.afternoon");
  return t("header.greeting.evening");
}

export default function Header({ onMenu, collapsed = false, onToggleCollapse }) {
  const { range, setRange } = useDashboard();
  const navigate = useNavigate();
  const t = useT();
  const { theme, setTheme } = useTheme();
  const { lang, setLang } = useI18n();
  const [searchOpen, setSearchOpen] = useState(false);
  const currentRange = DATE_RANGES.find((r) => r.id === range) || DATE_RANGES[3];

  return (
    <header className="sticky top-0 z-20 bg-background/80 backdrop-blur-md border-b border-border">
      <div className="h-16 px-4 sm:px-6 flex items-center gap-3">
        <button
          onClick={onMenu}
          className="lg:hidden h-9 w-9 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Collapse toggle — desktop only */}
        <button
          onClick={onToggleCollapse}
          title={collapsed ? t("sidebar.expand") : t("sidebar.collapse")}
          className="hidden lg:grid h-9 w-9 place-items-center rounded-lg border border-border hover:bg-surface text-muted-foreground cursor-pointer"
        >
          <PanelLeft className={cn("h-[18px] w-[18px] transition-transform", collapsed && "rotate-180")} />
        </button>

        {/* Search */}
        <div className="flex-1 max-w-md mx-auto lg:mx-4 hidden sm:block">
          <GlobalSearch />
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <TokenIndicator />

          {/* Theme — click to toggle light/dark */}
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title={t(theme === "dark" ? "appearance.theme.light" : "appearance.theme.dark")}
            className="h-9 w-9 grid place-items-center rounded-lg border border-border hover:bg-surface cursor-pointer"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

          {/* Language — click to toggle */}
          <button
            onClick={() => setLang(lang === "en" ? "ar" : "en")}
            title={t(`appearance.language.${lang === "en" ? "ar" : "en"}`)}
            className="h-9 w-9 grid place-items-center rounded-lg border border-border text-[13px] font-medium hover:bg-surface cursor-pointer"
          >
            <Languages className="h-4 w-4" />
          </button>

          {/* Date range */}
          <Dropdown
            width="w-44"
            trigger={(open) => (
              <span className="flex items-center justify-center gap-1.5 h-9 min-w-[150px] px-3 rounded-lg border border-border text-[13px] font-medium hover:bg-surface cursor-pointer whitespace-nowrap">
                {t(`range.${currentRange.id}`)}
                <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
              </span>
            )}
          >
            {(close) =>
              DATE_RANGES.map((r) => (
                <button
                  key={r.id}
                  onClick={() => {
                    setRange(r.id);
                    close();
                  }}
                  className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[13px] hover:bg-surface text-left"
                >
                  {t(`range.${r.id}`)}
                  {r.id === range && <Check className="h-4 w-4 text-primary" />}
                </button>
              ))
            }
          </Dropdown>

          {/* Mobile search toggle */}
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className="sm:hidden h-9 w-9 grid place-items-center rounded-lg border border-border hover:bg-surface text-muted-foreground"
          >
            <Search className="h-4 w-4" />
          </button>

          {/* Notifications */}
          <Dropdown
            width="w-72"
            align="right"
            trigger={() => (
              <span className="h-9 w-9 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground relative cursor-pointer">
                <Bell className="h-[18px] w-[18px]" />
                <span className="absolute top-2 right-2.5 h-1.5 w-1.5 rounded-full bg-primary" />
              </span>
            )}
          >
            {(close) => (
              <>
                <div className="px-2.5 py-1.5 flex items-center justify-between">
                  <span className="text-[13px] font-semibold">{t("notifications.title")}</span>
                  <button
                    onClick={close}
                    className="text-[11.5px] text-primary font-medium hover:underline"
                  >
                    {t("notifications.markAll")}
                  </button>
                </div>
                <div className="max-h-80 overflow-y-auto scrollbar-thin">
                  {NOTIFICATIONS.map((n, i) => (
                    <a
                      key={i}
                      href={n.to}
                      onClick={(e) => { e.preventDefault(); close(); navigate(n.to); }}
                      className="flex gap-2.5 px-2.5 py-2 rounded-lg hover:bg-surface"
                    >
                      <span className={cn("mt-1 h-1.5 w-1.5 rounded-full shrink-0", n.tone === "primary" ? "bg-primary" : n.tone === "warning" ? "bg-warning" : "bg-success")} />
                      <div className="min-w-0">
                        <div className="text-[12.5px] font-medium leading-snug">{t(`notifications.item.${n.id}.title`)}</div>
                        <div className="text-[11.5px] text-muted-foreground leading-snug">{t(`notifications.item.${n.id}.body`)}</div>
                      </div>
                    </a>
                  ))}
                </div>
              </>
            )}
          </Dropdown>

          {/* Help */}
          <Dropdown
            width="w-56"
            align="right"
            trigger={() => (
              <span className="h-9 w-9 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground cursor-pointer hidden sm:grid">
                <CircleHelp className="h-[18px] w-[18px]" />
              </span>
            )}
          >
            {(close) => (
              <>
                {HELP_ITEMS.map((h) => (
                  <button
                    key={h.to}
                    onClick={() => { close(); navigate(h.to); }}
                    className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-[13px] hover:bg-surface text-left"
                  >
                    <h.icon className="h-4 w-4 text-muted-foreground" />
                    {t(`help.${h.id}`)}
                  </button>
                ))}
              </>
            )}
          </Dropdown>
        </div>

        {/* Greeting — far right */}
        <div className="hidden md:block shrink-0 w-[210px] text-right">
          <div className="font-display text-[17px] font-semibold leading-tight whitespace-nowrap truncate">
            {greeting(t)}, Ahmed
          </div>
          <div className="text-[12px] text-muted-foreground leading-tight whitespace-nowrap truncate">
            {t("header.greetingUser")}
          </div>
        </div>
      </div>
      {searchOpen && (
        <div className="sm:hidden px-4 pb-3">
          <GlobalSearch autoFocus onPick={() => setSearchOpen(false)} />
        </div>
      )}
    </header>
  );
}