"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  LayoutDashboard,
  MessagesSquare,
  Bell,
  Users,
  ShoppingCart,
  Package,
  Warehouse,
  Megaphone,
  Sparkles,
  Settings,
  Plus,
  Search,
  CornerDownLeft,
  Scale,
  Receipt,
} from "lucide-react";
import { t } from "@/lib/t";
import { cn } from "@/lib/utils";
import { useGlobalSearch } from "@/lib/queries";

/** Command palette (§96) — Cmd+K للتنقل والإجراءات السريعة. */

type CommandItem = {
  id: string;
  label: string;
  group: "nav" | "actions" | "search";
  icon: React.ReactNode;
  keywords?: string;
  href: string;
};

/* Built at render time (not module scope) so the labels follow the active
   language without a page reload. */
function buildNavItems(): CommandItem[] {
  return [
    { id: "nav-dashboard", label: t.goDashboard, group: "nav", href: "/dashboard", icon: <LayoutDashboard aria-hidden="true" />, keywords: "شغلي نظرة عامة overview home" },
    { id: "nav-inbox", label: t.goInbox, group: "nav", href: "/inbox", icon: <MessagesSquare aria-hidden="true" />, keywords: "whatsapp telegram محادثة" },
    { id: "nav-approvals", label: t.approvalsTitle, group: "nav", href: "/approvals", icon: <Scale aria-hidden="true" />, keywords: "موافقات اعتماد" },
    { id: "nav-customers", label: t.goCustomers, group: "nav", href: "/customers", icon: <Users aria-hidden="true" />, keywords: "عميل ليد" },
    { id: "nav-orders", label: t.goOrders, group: "nav", href: "/orders", icon: <ShoppingCart aria-hidden="true" />, keywords: "طلب" },
    { id: "nav-products", label: t.goProducts, group: "nav", href: "/products", icon: <Package aria-hidden="true" />, keywords: "منتج" },
    { id: "nav-inventory", label: t.goInventory, group: "nav", href: "/inventory", icon: <Warehouse aria-hidden="true" />, keywords: "مخزون رصيد" },
    { id: "nav-marketing", label: t.goMarketing, group: "nav", href: "/marketing", icon: <Megaphone aria-hidden="true" />, keywords: "حملة اعلان" },
    { id: "nav-financial", label: t.financial, group: "nav", href: "/financial", icon: <Receipt aria-hidden="true" />, keywords: "مالية حسابات قيود ledger balance" },
    { id: "nav-ai", label: t.agentSettings, group: "nav", href: "/ai", icon: <Sparkles aria-hidden="true" />, keywords: "معرفة وكيل agent prompt" },
    { id: "nav-analytics", label: t.dashboards, group: "nav", href: "/analytics", icon: <LayoutDashboard aria-hidden="true" />, keywords: "تحليلات بيانات analytics" },
    { id: "nav-settings", label: t.goSettings, group: "nav", href: "/settings", icon: <Settings aria-hidden="true" />, keywords: "اعدادات دعوة تكامل" },
    { id: "nav-notifications", label: t.notifications, group: "nav", href: "/notifications", icon: <Bell aria-hidden="true" />, keywords: "اشعارات تنبيهات" },
  ];
}

function buildActionItems(): CommandItem[] {
  return [
    { id: "act-order", label: t.newOrder, group: "actions", href: "/orders?new=1", icon: <Plus aria-hidden="true" />, keywords: "طلب جديد create" },
    { id: "act-product", label: t.newProduct, group: "actions", href: "/products?new=1", icon: <Plus aria-hidden="true" />, keywords: "منتج جديد create" },
    { id: "act-task", label: t.newTask, group: "actions", href: "/tasks?new=1", icon: <Plus aria-hidden="true" />, keywords: "مهمة جديدة create" },
    { id: "act-campaign", label: t.newCampaign, group: "actions", href: "/marketing?new=1", icon: <Plus aria-hidden="true" />, keywords: "حملة اعلان create" },
    { id: "act-knowledge", label: t.newKnowledge, group: "actions", href: "/ai?new=1", icon: <Plus aria-hidden="true" />, keywords: "معرفة سؤال create" },
    { id: "act-invite", label: t.newInvitation, group: "actions", href: "/settings?new=1", icon: <Plus aria-hidden="true" />, keywords: "دعوة فريق create" },
  ];
}

/** تطبيع عربي بسيط للبحث (همزات، تاء مربوطة، ألف مقصورة، تشكيل). */
function normalizeArabic(s: string) {
  return s
    .toLowerCase()
    .replace(/[\u064B-\u0652\u0670]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .replace(/[ً-ْ]/g, "")
    .trim();
}

function matches(query: string, item: CommandItem) {
  const q = normalizeArabic(query);
  if (!q) return true;
  const haystack = normalizeArabic(`${item.label} ${item.keywords ?? ""}`);
  // substring ثم subsequence كخطة بديلة
  if (haystack.includes(q)) return true;
  let i = 0;
  for (const ch of haystack) {
    if (ch === q[i]) i++;
    if (i === q.length) return true;
  }
  return false;
}

/** Where a search hit opens.
 *
 *  The SearchPort only ever returns `customer` and `product` today (see
 *  core/search.py). A customer opens its 360 record — before that page existed
 *  this pointed at the list and silently dropped the hit. The other branches
 *  stay as list fallbacks because no detail route exists for them.
 */
function listRouteFor(entityType: string): string {
  switch (entityType) {
    case "customer":
      return "/customers";
    case "order":
      return "/orders";
    case "task":
      return "/tasks";
    case "product":
      return "/products";
    case "conversation":
      return "/inbox";
    default:
      return "/dashboard";
  }
}

/** Where a search hit opens: its own record when one exists, its list otherwise.
 *
 *  Exported because "a hit dropped its entity_id" is invisible to every other
 *  tool in the repo — `scripts/check-search-hits.mjs` imports this function and
 *  clicks a rendered row with it (gap F7).
 *
 *  A hit whose id is missing or empty can only open its list: interpolating it
 *  would build `/customers/undefined`, or a trailing slash that matches no
 *  route at all. */
export function searchHref(entityType: string, entityId: string | null | undefined) {
  const raw = typeof entityId === "string" ? entityId.trim() : "";
  if (!raw) return listRouteFor(entityType);
  const id = encodeURIComponent(raw);
  switch (entityType) {
    case "customer":
      return `/customers/${id}`;
    case "order":
      // The order detail screen exists (`(dash)/orders/[id]`), so a hit that
      // named an order and opened the list was throwing the id away.
      return `/orders/${id}`;
    case "conversation":
      return `/inbox?conversation=${id}`;
    default:
      // products and tasks have no `[id]` route yet: the list is the truth.
      return listRouteFor(entityType);
  }
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const globalSearch = useGlobalSearch();
  // مراجع ثابتة — الكائن نفسه يتغير كل render وهذا كان يسبب حلقة طلبات
  const { mutate: runGlobalSearch, reset: resetGlobalSearch } = globalSearch;

  // Built each render so a language switch is reflected immediately.
  const navItems = buildNavItems();
  const actionItems = buildActionItems();

  const results: CommandItem[] = [
    ...navItems.filter((i) => matches(query, i)),
    ...actionItems.filter((i) => matches(query, i)),
    ...(globalSearch.data ?? []).map((hit) => ({
      id: `search-${hit.entity_type}-${hit.entity_id}`,
      label: hit.title,
      group: "search" as const,
      href: searchHref(hit.entity_type, hit.entity_id),
      icon: <Search aria-hidden="true" />,
      keywords: hit.snippet ?? hit.entity_type,
    })),
  ];

  React.useEffect(() => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      resetGlobalSearch();
      return;
    }
    const timer = window.setTimeout(() => runGlobalSearch(normalized), 250);
    return () => window.clearTimeout(timer);
  }, [runGlobalSearch, resetGlobalSearch, query]);

  React.useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
    }
  }, [open]);

  function run(item: CommandItem) {
    onOpenChange(false);
    router.push(item.href);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % Math.max(1, results.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % Math.max(1, results.length));
    } else if (e.key === "Enter" && results[active]) {
      e.preventDefault();
      run(results[active]);
    }
  }

  const navResults = results.filter((i) => i.group === "nav");
  const actionResults = results.filter((i) => i.group === "actions");
  const searchResults = results.filter((i) => i.group === "search");
  const activeId = results[active] ? `command-option-${active}` : undefined;
  let flatIndex = -1;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[60] bg-foreground/30 backdrop-blur-[2px] data-[state=open]:animate-[overlay-in_200ms_var(--ease-smooth)]" />
        <DialogPrimitive.Content
          dir="rtl"
          aria-label={t.search}
          onKeyDown={onKeyDown}
          className={cn(
            "fixed left-1/2 top-[18%] z-[70] w-full max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-card shadow-lg",
            "data-[state=open]:animate-[dialog-in_200ms_var(--ease-smooth)] data-[state=closed]:animate-[dialog-out_150ms_var(--ease-smooth)]",
          )}
        >
          <DialogPrimitive.Title className="sr-only">{t.search}</DialogPrimitive.Title>
          <div className="flex items-center gap-3 border-b border-border px-4">
            <Search aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              role="combobox"
              aria-expanded
              aria-controls="command-list"
              aria-activedescendant={activeId}
              aria-autocomplete="list"
              aria-label={t.search}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              placeholder={t.searchPlaceholder}
              className="h-12 w-full bg-transparent text-[15px] outline-none placeholder:text-muted-foreground/70"
              data-testid="command-input"
            />
            <kbd className="shrink-0 rounded-md border border-border border-b-2 px-1.5 py-0.5 text-[11px] font-bold text-muted-foreground" dir="ltr">
              Esc
            </kbd>
          </div>

          <div
            id="command-list"
            role="listbox"
            aria-label={t.search}
            className="max-h-80 overflow-y-auto p-2"
            data-testid="command-list"
          >
            {results.length === 0 && !globalSearch.isPending && (
              <p className="px-3 py-8 text-center text-[13px] text-muted-foreground">{t.noResultsFound}</p>
            )}

            {globalSearch.isPending && <p className="px-3 py-3 text-xs text-muted-foreground">{t.searching}</p>}

            {navResults.length > 0 && (
              <div role="group" aria-label={t.navigation}>
                <p aria-hidden="true" className="px-3 pb-1 pt-2 text-xs font-bold text-muted-foreground">{t.navigation}</p>
                {navResults.map((item) => {
                  flatIndex++;
                  const idx = flatIndex;
                  return <CommandRow key={item.id} id={`command-option-${idx}`} item={item} active={idx === active} onRun={() => run(item)} onHover={() => setActive(idx)} />;
                })}
              </div>
            )}

            {actionResults.length > 0 && (
              <div role="group" aria-label={t.quickActions}>
                <p aria-hidden="true" className="px-3 pb-1 pt-2 text-xs font-bold text-muted-foreground">{t.quickActions}</p>
                {actionResults.map((item) => {
                  flatIndex++;
                  const idx = flatIndex;
                  return <CommandRow key={item.id} id={`command-option-${idx}`} item={item} active={idx === active} onRun={() => run(item)} onHover={() => setActive(idx)} />;
                })}
              </div>
            )}

            {searchResults.length > 0 && (
              <div role="group" aria-label={t.searchResults}>
                <p aria-hidden="true" className="px-3 pb-1 pt-2 text-xs font-bold text-muted-foreground">{t.searchResults}</p>
                {searchResults.map((item) => {
                  flatIndex++;
                  const idx = flatIndex;
                  return <CommandRow key={item.id} id={`command-option-${idx}`} item={item} active={idx === active} onRun={() => run(item)} onHover={() => setActive(idx)} />;
                })}
              </div>
            )}
          </div>

          <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-[11.5px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <CornerDownLeft className="size-3.5" aria-hidden="true" />
              {t.toOpen}
            </span>
            <span className="flex items-center gap-1.5" dir="ltr">
              ↑ ↓
            </span>
            <span className="ms-auto" dir="ltr">
              ⌘K
            </span>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function CommandRow({
  id,
  item,
  active,
  onRun,
  onHover,
}: {
  id: string;
  item: CommandItem;
  active: boolean;
  onRun: () => void;
  onHover: () => void;
}) {
  return (
    <button
      type="button"
      id={id}
      role="option"
      aria-selected={active}
      tabIndex={-1}
      onClick={onRun}
      onMouseMove={onHover}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-start text-sm font-medium transition-colors duration-150 ease-smooth",
        active ? "bg-primary-soft text-primary" : "hover:bg-muted",
      )}
      data-testid={`command-${item.id}`}
    >
      <span className={cn("[&_svg]:size-4", active ? "text-primary" : "text-muted-foreground")}>{item.icon}</span>
      <span className="flex-1 truncate">{item.label}</span>
      {active && <CornerDownLeft className="size-3.5 text-primary" aria-hidden="true" />}
    </button>
  );
}
