import React, { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import Sidebar from "./Sidebar";
import Header from "./Header";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

export default function DashboardLayout() {
  const { pathname } = useLocation();
  const { lang } = useI18n();
  const isDashboardHome = pathname === "/dashboard";
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("fihrist:sidebarCollapsed") === "1";
  });

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem("fihrist:sidebarCollapsed", next ? "1" : "0"); } catch {}
      return next;
    });
  };

  return (
    <div data-dashboard-theme-scope className="min-h-screen bg-background">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
      <div className={cn("transition-[padding] duration-300", collapsed ? "lg:pl-[68px]" : "lg:pl-[248px]")}>
        {isDashboardHome ? (
          <Header onMenu={() => setSidebarOpen(true)} />
        ) : (
          <div className="flex h-12 items-center px-4 sm:px-6 lg:hidden">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label={lang === "ar" ? "فتح القائمة" : "Open navigation menu"}
              className="grid h-9 w-9 place-items-center rounded-lg border border-border text-muted-foreground hover:bg-surface"
            >
              <Menu className="h-5 w-5" />
            </button>
          </div>
        )}
        <main className="w-full min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
