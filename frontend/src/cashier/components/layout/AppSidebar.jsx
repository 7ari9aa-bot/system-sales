import { Link, useLocation } from "react-router-dom";
import { ChevronsLeft, ChevronsRight, Shirt, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Avatar, AvatarFallback } from "@/cashier/components/ui/avatar";
import { Button } from "@/cashier/components/ui/button";
import { Sheet, SheetContent } from "@/cashier/components/ui/sheet";
import { navGroups } from "@/cashier/components/layout/navItems";
import { shop } from "@/cashier/lib/mockData";
import { cn } from "@/cashier/lib/utils";

const STORAGE_KEY = "boutique-sidebar-collapsed";

// بند واحد في القائمة الجانبية (يظهر بالأيقونة فقط عند الطي).
function SidebarLink({ item, pathname, onNavigate, collapsed }) {
  const Icon = item.icon;
  const active = pathname === item.to || pathname.startsWith(`${item.to}/`);

  return (
    <li>
      <Link
        to={`/cashier${item.to}`}
        onClick={onNavigate}
        title={collapsed ? item.label : undefined}
        aria-label={item.label}
        className={cn(
          "relative flex items-center gap-2 rounded-lg text-[13px] transition-colors",
          collapsed ? "justify-center px-0 py-2" : "px-2 py-1.5",
          active ? "bg-accent font-semibold text-primary" : "text-foreground/80 hover:bg-muted/60 hover:text-foreground",
        )}
      >
        {active && <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-primary" aria-hidden="true" />}
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {!collapsed && <span className="truncate">{item.label}</span>}
      </Link>
    </li>
  );
}

function SidebarContent({ onNavigate, collapsed = false, onToggleCollapse }) {
  // الكاشير مركّب تحت /cashier داخل النظام الرئيسي، فنقارن بالمسار بعد البادئة.
  const pathname = useLocation().pathname.replace(/^\/cashier/, "") || "/";
  // الحساب يأتي من النظام الرئيسي لاحقاً؛ حالياً اسم ثابت للعرض فقط.
  const displayName = "مستخدم النظام";
  const initials = displayName
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("");

  return (
    <div className="flex h-full flex-col bg-card">
      <div className={cn("flex items-center border-b border-border", collapsed ? "flex-col gap-2 px-2 py-2.5" : "gap-2.5 px-3 py-3")}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <Shirt className="h-5 w-5" aria-hidden="true" />
        </span>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate font-heading text-sm font-extrabold">{shop.name}</p>
            <p className="truncate text-[11px] text-muted-foreground">نظام المبيعات والمخزون</p>
          </div>
        )}
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            title={collapsed ? "توسيع القائمة" : "طي القائمة"}
            aria-label={collapsed ? "توسيع القائمة" : "طي القائمة"}
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              !collapsed && "ms-auto",
            )}
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          </button>
        )}
      </div>

      <nav className={cn("flex-1 overflow-y-auto scroll-slim py-3", collapsed ? "px-1.5" : "px-2")}>
        {navGroups.map((group, index) => (
          <div key={index}>
            {index > 0 && <div className="my-2 h-px bg-border" role="separator" />}
            {!collapsed && group.title && <p className="px-2 py-0.5 text-[11px] font-bold text-primary">{group.title}</p>}
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <SidebarLink key={item.to} item={item} pathname={pathname} onNavigate={onNavigate} collapsed={collapsed} />
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-2">
        <div className={cn("flex items-center gap-2", collapsed && "flex-col gap-1")}>
          <Avatar className="h-8 w-8 shrink-0">
            <AvatarFallback className="bg-primary/10 text-[11px] font-bold text-primary">{initials || "؟"}</AvatarFallback>
          </Avatar>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold">{displayName}</p>
              <p className="truncate text-[10px] text-muted-foreground">مدير النظام</p>
            </div>
          )}
        </div>

        {!collapsed && (
          <div className="mt-2 rounded-lg bg-accent/60 p-2.5">
            <p className="flex items-center gap-1.5 text-[11px] font-bold text-accent-foreground">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              نسخة تجريبية للتصميم
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">كل البيانات المعروضة تجريبية لعرض الواجهات فقط.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// القائمة الجانبية: قابلة للطي على الكمبيوتر، ودرج منسدل على الموبايل.
export default function AppSidebar({ mobileOpen, onMobileOpenChange }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* تجاهل: القائمة تظل مفتوحة */
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* تجاهل */
      }
      return next;
    });
  }

  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 border-r border-border transition-[width] duration-200 lg:block",
          collapsed ? "w-[68px]" : "w-[236px]",
        )}
      >
        <div className="sticky top-0 h-screen">
          <SidebarContent collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
        </div>
      </aside>
      <Sheet open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <SheetContent side="left" className="w-[280px] p-0">
          <SidebarContent onNavigate={() => onMobileOpenChange?.(false)} />
        </SheetContent>
      </Sheet>
    </>
  );
}