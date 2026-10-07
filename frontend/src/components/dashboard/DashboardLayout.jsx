import React, { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Header from "./Header";
import { DashboardProvider } from "@/lib/dashboardContext";
import { cn } from "@/lib/utils";

export default function DashboardLayout() {
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
    <DashboardProvider>
      <div data-dashboard-theme-scope className="min-h-screen bg-background">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
        <div className={cn("transition-[padding] duration-300", collapsed ? "lg:pl-[68px]" : "lg:pl-[248px]")}>
          <Header onMenu={() => setSidebarOpen(true)} />
          <main className="w-full min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </DashboardProvider>
  );
}
