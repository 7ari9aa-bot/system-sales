import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ScanLine,
  Plus,
  Minus,
  Trash2,
  ShoppingCart,
  Loader2,
  Percent,
  PauseCircle,
  PlayCircle,
  Undo2,
  Lock,
  ArrowLeftRight,
  Search,
  Package,
  FileText,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { money, utcDay } from "@/components/pos/money";
import OpenShiftPanel from "@/components/pos/OpenShiftPanel";
import PaymentPanel from "@/components/pos/PaymentPanel";
import ClosePanel from "@/components/pos/ClosePanel";
import ReturnsPanel from "@/components/pos/ReturnsPanel";
import ReceiptView from "@/components/pos/ReceiptView";
import useRealtime from "@/hooks/useRealtime";

/** نظام الكاشير — طبقة البيع كاملة فوق /api/v1/pos.
 *
 * المسار الواحد: افتح الوردية (بروفايل + رصيد لكل وسيلة) → امسح أو دوّر →
 * سلة → تقسيمة دفع → إيصال حراري. والوردية بتتكفل برجوعها بعد أي refresh،
 * والمرتجع بسطوره، والتسليم بين الكاشيرين، والقفل بمطابقة لكل وسيلة.
 *
 * كل فلوس نصوص Decimal من الخادم — مفيش floats. مفيش نجاح بيتقال غير من
 * رد الخادم نفسه (قاعدة frontend/AGENTS.md). */

const POS_API = "/pos";

export default function POS() {
  const t = useT();

  const [registers, setRegisters] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [session, setSession] = useState(null);
  const [profile, setProfile] = useState(null);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const [tab, setTab] = useState("scan"); // scan | browse
  const [barcode, setBarcode] = useState("");
  const [browseQ, setBrowseQ] = useState("");
  const [browseItems, setBrowseItems] = useState([]);
  const [browseLoading, setBrowseLoading] = useState(false);

  const [lines, setLines] = useState([]);
  const [heldCartId, setHeldCartId] = useState(null);
  const [held, setHeld] = useState([]);
  const [discount, setDiscount] = useState("");
  const [tenders, setTenders] = useState([]);
  const [quote, setQuote] = useState(null);
  const [lastReceiptId, setLastReceiptId] = useState(null);

  const [showClose, setShowClose] = useState(false);
  const [closedReport, setClosedReport] = useState(null);
  const [showReturns, setShowReturns] = useState(false);
  const [showHandover, setShowHandover] = useState(false);
  const [grantees, setGrantees] = useState([]);
  const [handoverTo, setHandoverTo] = useState("");
  const [handoverCounted, setHandoverCounted] = useState("");

  const scanRef = React.useRef(null);

  // ------------------------------------------------------------------ load -

  const loadBootstrap = useCallback(async () => {
    try {
      const [regs, profs, openSessions] = await Promise.all([
        api(`${POS_API}/registers`),
        api(`${POS_API}/profiles`),
        api(`${POS_API}/sessions?status=OPEN`),
      ]);
      setRegisters(Array.isArray(regs) ? regs : []);
      setProfiles(Array.isArray(profs) ? profs : []);
      const open = Array.isArray(openSessions) ? openSessions : [];
      if (open.length > 0) {
        // آخر وردية مفتوحة — برجوع ليها فوراً (شاشة الكاشير مبتضيعش شيفت).
        resumeSession(open[0]);
      }
      setError(null);
    } catch (e) {
      setError(e?.message || t("pos.err.registers", "Could not load registers."));
    }
     
  }, []);

  useEffect(() => {
    void loadBootstrap();
  }, [loadBootstrap]);

  async function resumeSession(openSession) {
    setSession(openSession);
    setProfile(null);
    setClosedReport(null);
    setStale(utcDay(openSession.opened_at) !== utcDay(new Date().toISOString()));
    if (openSession.profile_id) {
      try {
        setProfile(await api(`${POS_API}/profiles/${openSession.profile_id}`));
      } catch {
        setProfile(null);
      }
    }
  }

  const loadHeld = useCallback(async () => {
    if (!session?.id) return;
    try {
      const rows = await api(`${POS_API}/sessions/${session.id}/held-carts`);
      setHeld(Array.isArray(rows) ? rows : []);
    } catch {
      setHeld([]);
    }
  }, [session?.id]);

  useEffect(() => {
    void loadHeld();
  }, [loadHeld]);

  // ------------------------------------------------------------------ open -

  async function openShift({ registerId, profileId, floatsByMethod, openingFloat }) {
    setBusy(true);
    setError(null);
    try {
      const created = await api(`${POS_API}/registers/${registerId}/sessions`, {
        method: "POST",
        body: {
          opening_float: openingFloat,
          profile_id: profileId || undefined,
          floats_by_method: floatsByMethod || undefined,
        },
      });
      await resumeSession(created);
      setLines([]);
      setQuote(null);
      setTenders([]);
      setLastReceiptId(null);
      setNotice(t("pos.opened", "Drawer open — good shift."));
    } catch (e) {
      setError(e?.message || t("pos.err.open", "Could not open the drawer."));
    } finally {
      setBusy(false);
    }
  }

  // ----------------------------------------------------------------- scan -

  async function doScan(e) {
    e?.preventDefault?.();
    const value = barcode.trim();
    if (!value || !session?.id || session.status !== "OPEN") return;
    setError(null);
    try {
      const found = await api(`${POS_API}/sessions/${session.id}/scan`, {
        method: "POST",
        body: { identifier_type: "barcode", value },
      });
      if (!found.found) {
        setError(found.refusal || t("pos.err.notFound", "No product matches that code."));
        return;
      }
      addVariant(found);
      setBarcode("");
      scanRef.current?.focus();
    } catch (err) {
      setError(err?.message || t("pos.err.scan", "Could not scan that code."));
    }
  }

  function addVariant(found) {
    setLines((prev) => {
      const i = prev.findIndex((l) => l.variant_id === found.variant_id);
      if (i >= 0) {
        const next = [...prev];
        next[i] = { ...next[i], quantity: next[i].quantity + 1 };
        return next;
      }
      return [
        ...prev,
        {
          variant_id: found.variant_id,
          title: found.title,
          sku: found.sku,
          unit_price: found.unit_price,
          quantity: 1,
        },
      ];
    });
  }

  function setLineDiscount(variantId, raw) {
    // خصم القطعة: نسبة 0-100 — بتتنفذ في السطر وبتتخزن مع الأوردر.
    let v = String(raw).trim();
    if (v === "") {
      setLines((prev) =>
        prev.map((l) =>
          l.variant_id === variantId ? { ...l, discount_pct: "" } : l
        )
      );
      return;
    }
    let n = Number(v);
    if (!Number.isFinite(n)) n = 0;
    n = Math.min(100, Math.max(0, n));
    const pct = n.toFixed(2);
    setLines((prev) =>
      prev.map((l) =>
        l.variant_id === variantId ? { ...l, discount_pct: pct } : l
      )
    );
  }

  function step(variantId, delta) {
    setLines((prev) =>
      prev
        .map((l) => (l.variant_id === variantId ? { ...l, quantity: l.quantity + delta } : l))
        .filter((l) => l.quantity > 0)
    );
  }

  function removeLine(variantId) {
    setLines((prev) => prev.filter((l) => l.variant_id !== variantId));
  }

  // --------------------------------------------------------------- browse -

  const loadBrowse = useCallback(async () => {
    if (!session?.id || session.status !== "OPEN") return;
    setBrowseLoading(true);
    try {
      const page = await api(
        `${POS_API}/sessions/${session.id}/items?q=${encodeURIComponent(browseQ)}&limit=24`
      );
      setBrowseItems(Array.isArray(page.items) ? page.items : []);
    } catch (e) {
      setError(e?.message || t("pos.err.browse", "Could not load the products."));
    } finally {
      setBrowseLoading(false);
    }
     
  }, [session?.id, session?.status, browseQ]);

  useEffect(() => {
    if (tab === "browse") void loadBrowse();
  }, [tab, loadBrowse]);

  // ---------------------------------------------------------------- quote -

  const items = useMemo(
    () => lines.map((l) => ({ variant_id: l.variant_id, quantity: l.quantity })),
    [lines]
  );

  const refreshQuote = useCallback(async () => {
    if (!session?.id || items.length === 0) {
      setQuote(null);
      return;
    }
    try {
      const body = {
        items: items.map((it) => {
          const line = lines.find((l) => l.variant_id === it.variant_id);
          return line?.discount_pct
            ? { ...it, discount_pct: line.discount_pct }
            : it;
        }),
      };
      if (discount) body.discount_total = discount;
      const q = await api(`${POS_API}/sessions/${session.id}/quote`, { method: "POST", body });
      setQuote(q);
      setError(null);
    } catch (e) {
      setQuote(null);
      setError(e?.message || t("pos.err.quote", "Could not price the cart."));
    }
  }, [session?.id, items, discount, t]);

  useEffect(() => {
    void refreshQuote();
  }, [refreshQuote]);

  // ----------------------------------------------------------------- sell -

  async function sell() {
    if (!session?.id || items.length === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const body = {
        items: items.map((it) => {
          const line = lines.find((l) => l.variant_id === it.variant_id);
          return line?.discount_pct
            ? { ...it, discount_pct: line.discount_pct }
            : it;
        }),
        tenders: tenders.map((td) => ({ method: td.method, amount: td.amount })),
      };
      if (discount) {
        body.discount_total = discount;
      }
      if (heldCartId) body.held_cart_id = heldCartId;
      const result = await api(`${POS_API}/sessions/${session.id}/sell`, {
        method: "POST",
        body,
      });
      setLastReceiptId(result.receipt_id);
      setNotice(t("pos.sold", "Sale recorded. Receipt {n}.", { n: result.receipt_number }));
      setLines([]);
      setQuote(null);
      setTenders([]);
      setDiscount("");
      setHeldCartId(null);
      void loadHeld();
      scanRef.current?.focus();
    } catch (e) {
      setError(e?.message || t("pos.err.sell", "Could not record the sale."));
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------ held carts -

  async function holdCart() {
    if (!session?.id || items.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await api(`${POS_API}/sessions/${session.id}/held-carts`, {
        method: "POST",
        body: { items, label: t("pos.cartFor", "Cart of {n} items", { n: items.length }) },
      });
      setLines([]);
      setQuote(null);
      setHeldCartId(null);
      await loadHeld();
      setNotice(t("pos.held", "Cart parked."));
    } catch (e) {
      setError(e?.message || t("pos.err.hold", "Could not park the cart."));
    } finally {
      setBusy(false);
    }
  }

  function resumeCart(cart) {
    // الاسترجاع بقى ذرّي: سطور السلة بتبقى هي البيع، والخادم بيحجز السلة
    // جوه نفس الترانزاكشن — البيع هو اللي بيمسحها.
    setHeldCartId(cart.id);
    setLines(
      (cart.items || []).map((line) => ({
        variant_id: line.variant_id,
        title: null,
        sku: null,
        unit_price: null,
        quantity: line.quantity,
      }))
    );
    setDiscount(cart.discount_total ? String(cart.discount_total) : "");
    setNotice(t("pos.resumed", "Cart resumed — finish the sale to clear it."));
  }

  async function discardCart(cart) {
    setError(null);
    try {
      await api(`${POS_API}/held-carts/${cart.id}`, { method: "DELETE" });
      if (heldCartId === cart.id) {
        setHeldCartId(null);
        setLines([]);
        setQuote(null);
      }
      await loadHeld();
    } catch (e) {
      setError(e?.message || t("pos.err.resume", "Could not resume the cart."));
    }
  }

  // --------------------------------------------------------------- close --

  async function afterClose(closed) {
    setSession(closed);
    setShowClose(false);
    setStale(false);
    try {
      setClosedReport(await api(`${POS_API}/sessions/${closed.id}/report`));
    } catch {
      setClosedReport(null);
    }
    setNotice(t("pos.closed", "Drawer closed — variance {v}.", { v: money(closed.variance) }));
  }

  // ------------------------------------------------------------- realtime --

  // عين حية على الوردية: لو اتقفلت من تاب تاني أو من مدير، الشاشة هنا
  // بتتحدد فوراً بدل ما تفاجئ كاشير شغال (ERPNext بيعملها بـ frappe.realtime).
  useRealtime(
    ["pos_session.events"],
    (frame) => {
      const payload = frame?.payload || {};
      if (payload["pos.session.closed"] && payload.session_id === session?.id) {
        void (async () => {
          try {
            const fresh = await api(`${POS_API}/sessions/${session.id}`);
            if (fresh.status === "CLOSED") {
              await afterClose(fresh);
              setNotice(t("pos.shiftClosedRemote", "This shift was closed from somewhere else."));
            }
          } catch {
            /* الحالة هتتظبط في النداء الجاي */
          }
        })();
      }
    },
    Boolean(session?.id && session?.status === "OPEN")
  );

  // ------------------------------------------------------------ handover --

  async function toggleHandover() {
    const next = !showHandover;
    setShowHandover(next);
    if (next && profile?.id) {
      try {
        const rows = await api(`${POS_API}/profiles/${profile.id}/users`);
        setGrantees(Array.isArray(rows) ? rows : []);
      } catch {
        setGrantees([]);
      }
    } else if (next) {
      setGrantees([]);
    }
  }

  async function handover() {
    if (!session?.id || !handoverTo) return;
    setBusy(true);
    setError(null);
    try {
      await api(`${POS_API}/sessions/${session.id}/handover`, {
        method: "POST",
        body: { to_user_id: handoverTo, counted_cash: handoverCounted || "0.00" },
      });
      setSession((prev) => ({ ...prev, cashier_user_id: handoverTo }));
      setShowHandover(false);
      setHandoverTo("");
      setHandoverCounted("");
      setNotice(t("pos.handoverDone", "Drawer handed over."));
    } catch (e) {
      setError(e?.message || t("pos.err.handover", "Could not hand over the drawer."));
    } finally {
      setBusy(false);
    }
  }

  // --------------------------------------------------------------- render -

  const isOpen = session?.status === "OPEN";
  const canSellNow = isOpen && lines.length > 0 && !busy && !stale;

  // اختصارات الكاشير — نفس مجموعة ERPNext: Ctrl+I مسح، Ctrl+D خصم،
  // Ctrl+Enter تحصيل، Escape يقفل اللوحات المفتوحة.
  const sellRef = useRef(null);
  sellRef.current = () => {
    if (canSellNow) void sell();
  };
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") {
        setShowClose(false);
        setShowReturns(false);
        setShowHandover(false);
        return;
      }
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "i") {
        e.preventDefault();
        setTab("scan");
        scanRef.current?.focus();
      } else if (k === "d") {
        e.preventDefault();
        document.getElementById("pos-discount")?.focus();
      } else if (e.key === "Enter") {
        e.preventDefault();
        sellRef.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
     
  }, []);

  return (
    <div>
      <PageHeader
        title={t("pos.title", "Cashier")}
        subtitle={t("pos.subtitle", "Scan, take payment, print a receipt — one drawer at a time.")}
        actions={
          isOpen ? (
            <Badge tone="success">{t("pos.sessionOpen", "Drawer open")}</Badge>
          ) : session ? (
            <Badge tone="muted">{t("pos.sessionClosed", "Drawer closed")}</Badge>
          ) : null
        }
      />

      {error && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-success/30 bg-success/10 px-4 py-2.5 text-[13px] text-success">
          <span>{notice}</span>
        </div>
      )}
      {stale && (
        <div role="alert" className="mb-4 flex items-center gap-3 rounded-xl border border-warning/40 bg-warning/10 px-4 py-2.5 text-[13px] text-warning">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{t("pos.staleSession", "This shift was opened on a different day — close it and open a new one before selling.")}</span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-4">
          {/* يسار: مسح/تصفح + السلة */}
          <div className="space-y-4">
            <div className="rounded-2xl bg-card border border-border overflow-hidden">
              <div className="flex items-center border-b border-border">
                <button
                  type="button"
                  onClick={() => setTab("scan")}
                  className={cn(
                    "flex-1 px-4 py-2.5 text-[13px] font-medium inline-flex items-center justify-center gap-2",
                    tab === "scan" ? "bg-primary/5 text-primary" : "text-muted-foreground"
                  )}
                >
                  <ScanLine className="h-4 w-4" />
                  {t("pos.scanLabel", "Scan or type a barcode")}
                </button>
                <button
                  type="button"
                  onClick={() => setTab("browse")}
                  className={cn(
                    "flex-1 px-4 py-2.5 text-[13px] font-medium inline-flex items-center justify-center gap-2 border-s border-border",
                    tab === "browse" ? "bg-primary/5 text-primary" : "text-muted-foreground"
                  )}
                >
                  <Package className="h-4 w-4" />
                  {t("pos.browse", "Products")}
                </button>
              </div>

              {tab === "scan" ? (
                <form onSubmit={doScan} className="p-4">
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <ScanLine className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <input
                        ref={scanRef}
                        value={barcode}
                        onChange={(e) => setBarcode(e.target.value)}
                        placeholder={t("pos.scanPlaceholder", "Barcode…")}
                        dir="ltr"
                        disabled={!isOpen || stale}
                        className="h-11 w-full rounded-xl border border-border bg-surface ps-9 pe-3 text-[14px] tabular-nums"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={!isOpen || stale || !barcode.trim()}
                      className="h-11 px-4 rounded-xl bg-primary text-primary-foreground text-[13px] font-medium disabled:opacity-50"
                    >
                      {t("pos.add", "Add")}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="p-4">
                  <div className="relative mb-3">
                    <Search className="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      value={browseQ}
                      onChange={(e) => setBrowseQ(e.target.value)}
                      placeholder={t("pos.searchPlaceholder", "Search by name or SKU…")}
                      dir="auto"
                      className="h-11 w-full rounded-xl border border-border bg-surface ps-9 pe-3 text-[13px]"
                    />
                  </div>
                  {browseLoading ? (
                    <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                  ) : browseItems.length === 0 ? (
                    <p className="py-6 text-center text-[13px] text-muted-foreground">
                      {t("pos.emptyBrowse", "Nothing matches that search.")}
                    </p>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 max-h-80 overflow-y-auto">
                      {browseItems.map((item) => (
                        <button
                          key={item.variant_id}
                          type="button"
                          onClick={() =>
                            addVariant({
                              variant_id: item.variant_id,
                              title: item.title,
                              sku: item.sku,
                              unit_price: item.unit_price,
                            })
                          }
                          disabled={!isOpen || stale}
                          className="rounded-xl border border-border bg-surface p-3 text-start hover:border-primary/40 disabled:opacity-50"
                        >
                          <div className="text-[12.5px] font-medium truncate" dir="auto">
                            {item.title || item.sku}
                          </div>
                          <div className="text-[12px] text-muted-foreground tabular-nums" dir="ltr">
                            {money(item.unit_price)}
                          </div>
                          <div
                            className={cn(
                              "mt-1 inline-block rounded-lg px-1.5 py-0.5 text-[10.5px] tabular-nums",
                              item.available > 10
                                ? "bg-success/10 text-success"
                                : item.available > 0
                                  ? "bg-warning/10 text-warning"
                                  : "bg-destructive/10 text-destructive"
                            )}
                            dir="ltr"
                          >
                            {item.available > 0
                              ? t("pos.inStock", "{n} in stock", { n: item.available })
                              : t("pos.outOfStock", "Out of stock")}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="rounded-2xl bg-card border border-border overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <span className="inline-flex items-center gap-2 text-[13.5px] font-medium">
                  <ShoppingCart className="h-4 w-4" />
                  {t("pos.cart", "Cart")} · {lines.length}
                  {heldCartId && (
                    <Badge tone="warning">{t("pos.resumedBadge", "resumed")}</Badge>
                  )}
                </span>
                {lines.length > 0 && isOpen && !stale && (
                  <button
                    type="button"
                    onClick={() => void holdCart()}
                    className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground"
                  >
                    <PauseCircle className="h-4 w-4" />
                    {t("pos.hold", "Park")}
                  </button>
                )}
              </div>

              {lines.length === 0 ? (
                <div className="py-12 text-center text-[13px] text-muted-foreground">
                  {t("pos.emptyCart", "Scan an item to start the sale.")}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="text-muted-foreground text-[11px] uppercase tracking-wide border-b border-border">
                        <th className="text-start font-medium py-2 ps-4">{t("pos.col.item", "Item")}</th>
                        <th className="text-end font-medium py-2 px-2">{t("pos.col.price", "Price")}</th>
                        <th className="text-center font-medium py-2 px-2">{t("pos.col.qty", "Qty")}</th>
                        <th className="text-center font-medium py-2 px-2">{t("pos.col.discount", "Discount %")}</th>
                        <th className="text-end font-medium py-2 px-2">{t("pos.col.lineTotal", "Line total")}</th>
                        <th className="py-2 pe-3" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {lines.map((l) => {
                        const net = (Number(l.unit_price || 0) * l.quantity * (1 - Number(l.discount_pct || 0) / 100)).toFixed(2);
                        return (
                          <tr key={l.variant_id} className="hover:bg-surface/60">
                            <td className="py-2 ps-4 max-w-[220px]">
                              <div className="font-medium truncate" dir="auto">
                                {l.title || l.sku || `${l.variant_id.slice(0, 8)}…`}
                              </div>
                              <div className="text-[11px] text-muted-foreground tabular-nums" dir="ltr">
                                {l.sku || l.variant_id.slice(0, 8)}
                              </div>
                            </td>
                            <td className="text-end tabular-nums px-2" dir="ltr">{money(l.unit_price)}</td>
                            <td className="px-2">
                              <div className="flex items-center justify-center gap-1">
                                <button type="button" aria-label="Decrease" onClick={() => step(l.variant_id, -1)} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface">
                                  <Minus className="h-3 w-3" />
                                </button>
                                <span className="w-7 text-center tabular-nums">{l.quantity}</span>
                                <button type="button" aria-label="Increase" onClick={() => step(l.variant_id, 1)} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface">
                                  <Plus className="h-3 w-3" />
                                </button>
                              </div>
                            </td>
                            <td className="px-2 text-center">
                              <input
                                value={l.discount_pct ?? ""}
                                onChange={(e) => setLineDiscount(l.variant_id, e.target.value)}
                                placeholder="0"
                                title={t("pos.lineDiscount", "Line discount %")}
                                aria-label={t("pos.lineDiscount", "Line discount %")}
                                dir="ltr"
                                inputMode="decimal"
                                className="h-8 w-14 rounded-lg border border-border bg-surface px-1.5 text-[12px] tabular-nums text-center"
                              />
                            </td>
                            <td className="text-end tabular-nums px-2 font-medium" dir="ltr">{net}</td>
                            <td className="text-center pe-3">
                              <button type="button" aria-label="Remove" onClick={() => removeLine(l.variant_id)} className="h-7 w-7 grid place-items-center rounded-lg text-destructive hover:bg-destructive/10">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    <tfoot className="border-t-2 border-border bg-surface/50">
                      <tr>
                        <td colSpan={3} className="py-2.5 ps-4 text-[12.5px] text-muted-foreground">
                          {t("pos.col.pieces", "{n} pieces", { n: lines.reduce((a, l) => a + l.quantity, 0) })}
                        </td>
                        <td colSpan={3} className="text-end py-2.5 pe-3 font-semibold tabular-nums" dir="ltr">
                          {money(lines.reduce((a, l) => a + Number(l.unit_price || 0) * l.quantity, 0).toFixed(2))}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>

            {/* السلات المعلّقة */}
            {held.length > 0 && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <div className="text-[13px] font-medium mb-2 inline-flex items-center gap-2">
                  <PlayCircle className="h-4 w-4" />
                  {t("pos.heldCarts", "Parked carts")}
                </div>
                <ul className="flex flex-wrap gap-2">
                  {held.map((h) => (
                    <li key={h.id} className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => resumeCart(h)}
                        className={cn(
                          "rounded-xl border px-3 py-2 text-[12.5px]",
                          h.id === heldCartId
                            ? "border-primary bg-primary/5"
                            : "border-border bg-surface hover:border-primary/40"
                        )}
                      >
                        {h.label || t("pos.parked", "{n} items", { n: (h.items || []).length })}
                      </button>
                      <button
                        type="button"
                        aria-label={t("pos.discard", "Discard")}
                        onClick={() => void discardCart(h)}
                        className="h-8 w-8 grid place-items-center rounded-lg text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* المرتجعات */}
            {isOpen && !stale && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <button
                  type="button"
                  onClick={() => setShowReturns((v) => !v)}
                  className="w-full inline-flex items-center justify-between text-[13px] font-medium"
                >
                  <span className="inline-flex items-center gap-2">
                    <Undo2 className="h-4 w-4" />
                    {t("pos.refund", "Refund a sale")}
                  </span>
                  <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
                </button>
                {showReturns && (
                  <div className="mt-3">
                    <ReturnsPanel
                      sessionId={session.id}
                      onNotice={setNotice}
                      onError={setError}
                      onDone={(result) => {
                        if (result?.new_receipt_id) {
                          // الاستبدال بيطلع إيصالين — نعرض إيصال البيع الجديد.
                          setLastReceiptId(result.new_receipt_id);
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {/* يمين: فتح الوردية (بدون جلسة) + الإجمالي + الدفع + القفل */}
          <div className="space-y-4">
            {!session && (
              <OpenShiftPanel
                registers={registers}
                profiles={profiles}
                busy={busy}
                onOpen={(payload) => void openShift(payload)}
              />
            )}
            {session && (
            <>
            <div className="rounded-2xl bg-card border border-border p-4">
              <div className="text-[13px] font-medium mb-3">{t("pos.total", "Total")}</div>

              <label className="block text-[12.5px] text-muted-foreground mb-1.5 inline-flex items-center gap-1.5">
                <Percent className="h-3.5 w-3.5" />
                {t("pos.discount", "Discount")}
                {profile?.discount_ceiling_pct ? (
                  <span className="text-[11.5px]">
                    · {t("pos.ceiling", "ceiling {p}%", { p: profile.discount_ceiling_pct })}
                  </span>
                ) : null}
              </label>
              <input
                id="pos-discount"
                value={discount}
                onChange={(e) => setDiscount(e.target.value)}
                placeholder="0.00"
                dir="ltr"
                className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px] tabular-nums mb-3"
              />
              <dl className="space-y-1.5 mb-3 text-[13px]">
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">{t("pos.subtotal", "Subtotal")}</dt>
                  <dd className="tabular-nums" dir="ltr">{money(quote?.subtotal)}</dd>
                </div>
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">{t("pos.discountLabel", "Discount")}</dt>
                  <dd className="tabular-nums" dir="ltr">{money(quote?.discount_total)}</dd>
                </div>
                <div className="flex items-center justify-between border-t border-border pt-1.5">
                  <dt className="font-medium">{t("pos.grandTotal", "Total due")}</dt>
                  <dd className="font-display text-[18px] font-semibold tabular-nums" dir="ltr">
                    {money(quote?.grand_total)}
                  </dd>
                </div>
              </dl>

              <PaymentPanel
                quote={quote}
                methods={profile?.allowed_payment_methods || []}
                tenders={tenders}
                onTendersChange={setTenders}
                onSell={() => void sell()}
                busy={busy}
                discountBlocked={stale}
              />
            </div>

            {lastReceiptId && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <ReceiptView receiptId={lastReceiptId} onNotice={setNotice} />
              </div>
            )}

            {/* التسليم */}
            {isOpen && !stale && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <button
                  type="button"
                  onClick={() => void toggleHandover()}
                  className="w-full inline-flex items-center justify-between text-[13px] font-medium"
                >
                  <span className="inline-flex items-center gap-2">
                    <ArrowLeftRight className="h-4 w-4" />
                    {t("pos.handover", "Hand over the drawer")}
                  </span>
                </button>
                {showHandover && (
                  <div className="mt-3 space-y-2">
                    <select
                      value={handoverTo}
                      onChange={(e) => setHandoverTo(e.target.value)}
                      className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px]"
                    >
                      <option value="">{t("pos.handoverTo", "Hand to")}</option>
                      {grantees.map((g) => (
                        <option key={g.user_id} value={g.user_id}>
                          {g.full_name || `${g.user_id.slice(0, 8)}…`}
                        </option>
                      ))}
                    </select>
                    {grantees.length === 0 && (
                      <p className="text-[11.5px] text-muted-foreground">
                        {t("pos.noGrantees", "No grantees on this profile.")}
                      </p>
                    )}
                    <input
                      value={handoverCounted}
                      onChange={(e) => setHandoverCounted(e.target.value)}
                      placeholder={t("pos.handoverCounted", "Counted at handover")}
                      dir="ltr"
                      inputMode="decimal"
                      className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px] tabular-nums"
                    />
                    <button
                      type="button"
                      onClick={() => void handover()}
                      disabled={busy || !handoverTo}
                      className="h-10 w-full rounded-xl border border-border text-[13px] font-medium disabled:opacity-50"
                    >
                      {t("pos.handoverAction", "Hand over")}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* قفل الوردية */}
            {isOpen && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <button
                  type="button"
                  onClick={() => setShowClose((v) => !v)}
                  className="w-full inline-flex items-center justify-between text-[13px] font-medium"
                >
                  <span className="inline-flex items-center gap-2">
                    <Lock className="h-4 w-4" />
                    {t("pos.closeDrawer", "Close the drawer")}
                  </span>
                  <ArrowLeftRight className="h-4 w-4 text-muted-foreground" />
                </button>
                {showClose && (
                  <div className="mt-3">
                    <ClosePanel
                      sessionId={session.id}
                      onClosed={(closed) => void afterClose(closed)}
                      onError={setError}
                    />
                  </div>
                )}
              </div>
            )}

            {/* تقرير الوردية بعد القفل */}
            {closedReport && (
              <div className="rounded-2xl bg-card border border-border p-4">
                <div className="text-[13px] font-medium mb-2 inline-flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  {t("pos.report", "Shift report")}
                </div>
                <dl className="grid grid-cols-2 gap-y-1.5 text-[12.5px] mb-3">
                  <dt className="text-muted-foreground">{t("pos.invoices", "{n} sales", { n: closedReport.sales.invoice_count })}</dt>
                  <dd className="text-end tabular-nums" dir="ltr">{money(closedReport.sales.total)}</dd>
                  <dt className="text-muted-foreground">{t("pos.returnsTotal", "Returns")}</dt>
                  <dd className="text-end tabular-nums" dir="ltr">{money(closedReport.returns.total)}</dd>
                  <dt className="text-muted-foreground">{t("pos.expected", "Expected")}</dt>
                  <dd className="text-end tabular-nums" dir="ltr">{money(closedReport.expected_total ?? "—")}</dd>
                  <dt className="text-muted-foreground">{t("pos.variance", "Variance")}</dt>
                  <dd className={cn("text-end tabular-nums", Number(closedReport.variance_total || 0) !== 0 && "text-destructive")} dir="ltr">
                    {money(closedReport.variance_total ?? "—")}
                  </dd>
                </dl>
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="text-muted-foreground text-[11px] uppercase tracking-wide">
                      <th className="text-start font-medium py-1">{t("pos.method", "Method")}</th>
                      <th className="text-end font-medium py-1">{t("pos.expected", "Expected")}</th>
                      <th className="text-end font-medium py-1">{t("pos.counted", "Counted")}</th>
                      <th className="text-end font-medium py-1">{t("pos.variance", "Variance")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closedReport.by_method.map((r) => (
                      <tr key={r.method} className="border-t border-border">
                        <td className="py-1.5">{t(`pos.method.${r.method}`)}</td>
                        <td className="py-1.5 text-end tabular-nums" dir="ltr">{money(r.expected)}</td>
                        <td className="py-1.5 text-end tabular-nums" dir="ltr">{money(r.counted)}</td>
                        <td
                          className={cn(
                            "py-1.5 text-end tabular-nums",
                            r.variance != null && r.variance !== "0.00" && "text-destructive"
                          )}
                          dir="ltr"
                        >
                          {money(r.variance)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button
                  type="button"
                  onClick={() => {
                    setSession(null);
                    setClosedReport(null);
                    setProfile(null);
                  }}
                  className="mt-3 h-10 w-full rounded-xl bg-primary text-primary-foreground text-[13px] font-medium"
                >
                  {t("pos.newShift", "Start a new shift")}
                </button>
              </div>
            )}
            </>
            )}
          </div>
        </div>
    </div>
  );
}
