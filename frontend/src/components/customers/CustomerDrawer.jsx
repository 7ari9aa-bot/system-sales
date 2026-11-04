import React, { useEffect, useState } from "react";
import {
  X,
  Phone,
  Mail,
  MessageCircle,
  ShoppingBag,
  Clock,
  CheckCircle2,
  UserRound,
  ShieldAlert,
  ShieldCheck,
  Tag,
  Plus,
  Send,
  Receipt,
  FileText,
  Sparkles,
  Calendar,
  AlertCircle,
  Loader2,
} from "lucide-react";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const EVENT_ICONS = {
  order: ShoppingBag,
  conversation: MessageCircle,
  message: MessageCircle,
  task: CheckCircle2,
  note: UserRound,
  system: Sparkles,
};

function formatDate(value, lang = "ar") {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(lang === "ar" ? "ar-EG" : "en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CustomerDrawer({ customer, onClose, onCustomerUpdated }) {
  const _t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("overview"); // overview | orders | timeline | insights
  const [retryAttempt, setRetryAttempt] = useState(0);

  // Tags & Notes states
  const [newTag, setNewTag] = useState("");
  const [addingTag, setAddingTag] = useState(false);
  const [newNote, setNewNote] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [togglingBlock, setTogglingBlock] = useState(false);

  useEffect(() => {
    if (!customer?.id) {
      setRecord(null);
      return undefined;
    }
    let alive = true;
    setRecord(null);
    setError(null);
    setLoading(true);
    api(`/customers/${customer.id}/360?limit=50&timeline_limit=100`)
      .then((data) => {
        if (alive) setRecord(data);
      })
      .catch((e) => {
        if (alive) setError(e?.message || (isAr ? "تعذر تحميل بيانات العميل الكاملة." : "Could not load the customer record."));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [customer?.id, retryAttempt, isAr]);

  if (!customer) return null;

  const profile = record?.customer || customer;
  const isBlocked = Boolean(profile.is_blocked);
  const orders = record?.orders || [];
  const timeline = record?.timeline || [];
  const identities = record?.identities || [];
  const tags = record?.tags || [];
  const notes = record?.notes || [];

  const ltv = Number(profile.lifetime_value || 0);
  const ordersCount = orders.length || record?.stats?.orders_shown || 0;
  const aov = ordersCount > 0 ? ltv / ordersCount : 0;
  const isVip = ltv >= 1000 || ordersCount >= 3;

  // Toggle Block status
  async function handleToggleBlock() {
    if (togglingBlock || !customer?.id) return;
    setTogglingBlock(true);
    const action = isBlocked ? "unblock" : "block";
    try {
      const res = await api(`/customers/${customer.id}/${action}`, { method: "POST" });
      setRecord((prev) => prev ? { ...prev, customer: { ...prev.customer, is_blocked: res.is_blocked } } : prev);
      onCustomerUpdated?.({ ...customer, is_blocked: res.is_blocked });
    } catch (e) {
      alert(e?.message || (isAr ? "فشل تعديل حالة الحظر" : "Failed to update block state"));
    } finally {
      setTogglingBlock(false);
    }
  }

  // Add Tag
  async function handleAddTag(e) {
    e.preventDefault();
    const tagClean = newTag.trim();
    if (!tagClean || addingTag) return;
    setAddingTag(true);
    try {
      const added = await api(`/customers/${customer.id}/tags`, {
        method: "POST",
        body: { name: tagClean },
      });
      setRecord((prev) => ({
        ...prev,
        tags: [...(prev?.tags || []), added],
      }));
      setNewTag("");
    } catch (e) {
      alert(e?.message || (isAr ? "تعذر إضافة الوسم" : "Could not add tag"));
    } finally {
      setAddingTag(false);
    }
  }

  // Remove Tag
  async function handleRemoveTag(tagName) {
    try {
      await api(`/customers/${customer.id}/tags/${encodeURIComponent(tagName)}`, {
        method: "DELETE",
      });
      setRecord((prev) => ({
        ...prev,
        tags: (prev?.tags || []).filter((t) => t.name !== tagName),
      }));
    } catch (e) {
      alert(e?.message || (isAr ? "تعذر حذف الوسم" : "Could not remove tag"));
    }
  }

  // Add Internal Staff Note
  async function handleAddNote(e) {
    e.preventDefault();
    const noteClean = newNote.trim();
    if (!noteClean || addingNote) return;
    setAddingNote(true);
    try {
      const added = await api(`/customers/${customer.id}/notes`, {
        method: "POST",
        body: { body: noteClean },
      });
      setRecord((prev) => ({
        ...prev,
        notes: [added, ...(prev?.notes || [])],
        timeline: [
          {
            kind: "note",
            title: isAr ? "ملاحظة جديدة" : "New Note",
            subtitle: noteClean,
            at: new Date().toISOString(),
          },
          ...(prev?.timeline || []),
        ],
      }));
      setNewNote("");
    } catch (e) {
      alert(e?.message || (isAr ? "تعذر إضافة الملاحظة" : "Could not add note"));
    } finally {
      setAddingNote(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-in fade-in-50 duration-200" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-xs" />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="customer-profile-title"
        className="relative w-full max-w-2xl h-full bg-card border-l border-border shadow-2xl flex flex-col overflow-hidden text-foreground"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-20 bg-card/95 backdrop-blur-md px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-11 w-11 rounded-2xl bg-primary/10 text-primary grid place-items-center text-[15px] font-bold shrink-0">
              {String(profile.name || "C").trim().slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h3 id="customer-profile-title" className="font-display text-[17px] font-bold truncate">
                  {profile.name || (isAr ? "عميل غير مسمى" : "Unnamed Customer")}
                </h3>
                {isVip && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-semibold bg-amber-500/15 text-amber-600 border border-amber-500/30">
                    <Sparkles className="h-3 w-3" /> VIP
                  </span>
                )}
                {isBlocked ? (
                  <Badge tone="destructive">{isAr ? "محظور" : "Blocked"}</Badge>
                ) : (
                  <Badge tone="success">{isAr ? "نشط" : "Active"}</Badge>
                )}
              </div>
              <div className="text-[12px] text-muted-foreground truncate mt-0.5" dir="ltr">
                {profile.phone || profile.email || "—"}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {profile.phone && (
              <a
                href={`https://wa.me/${profile.phone.replace(/[^0-9]/g, "")}`}
                target="_blank"
                rel="noreferrer"
                title={isAr ? "مراسلة عبر واتساب" : "Message on WhatsApp"}
                className="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-[12px] font-medium flex items-center gap-1.5 transition-colors"
              >
                <MessageCircle className="h-3.5 w-3.5" />
                <span>{isAr ? "واتساب" : "WhatsApp"}</span>
              </a>
            )}
            <button
              type="button"
              disabled={togglingBlock}
              onClick={handleToggleBlock}
              title={isBlocked ? (isAr ? "إلغاء حظر العميل" : "Unblock customer") : (isAr ? "حظر العميل" : "Block customer")}
              className={cn(
                "h-8 px-2.5 rounded-lg border text-[12px] font-medium flex items-center gap-1 transition-colors",
                isBlocked
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20"
                  : "border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/20"
              )}
            >
              {isBlocked ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
              <span>{isBlocked ? (isAr ? "فك الحظر" : "Unblock") : (isAr ? "حظر" : "Block")}</span>
            </button>
            <button
              type="button"
              aria-label={isAr ? "إغلاق" : "Close"}
              onClick={onClose}
              className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Quick KPI Strip */}
        <div className="grid grid-cols-4 gap-3 px-6 py-3.5 bg-surface/40 border-b border-border text-center shrink-0">
          <div className="p-2 rounded-xl bg-card border border-border/80">
            <div className="text-[11px] text-muted-foreground">{isAr ? "إجمالي الإنفاق" : "Total Spent"}</div>
            <div className="font-display text-[15px] font-bold text-foreground tabular-nums mt-0.5">
              {formatCurrency(ltv)}
            </div>
          </div>
          <div className="p-2 rounded-xl bg-card border border-border/80">
            <div className="text-[11px] text-muted-foreground">{isAr ? "عدد الطلبات" : "Total Orders"}</div>
            <div className="font-display text-[15px] font-bold text-foreground tabular-nums mt-0.5">
              {ordersCount}
            </div>
          </div>
          <div className="p-2 rounded-xl bg-card border border-border/80">
            <div className="text-[11px] text-muted-foreground">{isAr ? "متوسط الطلب" : "Avg Order"}</div>
            <div className="font-display text-[15px] font-bold text-foreground tabular-nums mt-0.5">
              {formatCurrency(aov)}
            </div>
          </div>
          <div className="p-2 rounded-xl bg-card border border-border/80">
            <div className="text-[11px] text-muted-foreground">{isAr ? "تاريخ التسجيل" : "Customer Since"}</div>
            <div className="text-[12px] font-semibold text-foreground truncate mt-0.5">
              {profile.created_at ? new Date(profile.created_at).toLocaleDateString(isAr ? "ar-EG" : "en-US", { month: "short", year: "numeric" }) : "—"}
            </div>
          </div>
        </div>

        {/* Tabs Bar */}
        <div className="flex items-center gap-1 px-6 border-b border-border bg-card text-[13px] font-medium shrink-0">
          <button
            type="button"
            onClick={() => setActiveTab("overview")}
            className={cn(
              "py-3 px-3 border-b-2 transition-colors",
              activeTab === "overview"
                ? "border-primary text-primary font-semibold"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {isAr ? "نظرة عامة والهوية" : "Overview & Identities"}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("orders")}
            className={cn(
              "py-3 px-3 border-b-2 transition-colors flex items-center gap-1.5",
              activeTab === "orders"
                ? "border-primary text-primary font-semibold"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <span>{isAr ? "سجل المبيعات والطلبات" : "Orders & Purchases"}</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-surface font-semibold tabular-nums">{ordersCount}</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("timeline")}
            className={cn(
              "py-3 px-3 border-b-2 transition-colors",
              activeTab === "timeline"
                ? "border-primary text-primary font-semibold"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {isAr ? "السجل الزمني والنشاط" : "Activity Timeline"}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("insights")}
            className={cn(
              "py-3 px-3 border-b-2 transition-colors",
              activeTab === "insights"
                ? "border-primary text-primary font-semibold"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {isAr ? "سلوك العميل والتحليل" : "Insights & Habits"}
          </button>
        </div>

        {/* Tab Body */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
          {loading && (
            <div className="py-16 grid place-items-center text-muted-foreground gap-2">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
              <span className="text-[13px]">{isAr ? "جارٍ تحميل السجل الكامل للعميل…" : "Loading customer records…"}</span>
            </div>
          )}

          {error && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
              <button
                type="button"
                onClick={() => setRetryAttempt((a) => a + 1)}
                className="font-semibold underline shrink-0 hover:opacity-80"
              >
                {isAr ? "إعادة المحاولة" : "Retry"}
              </button>
            </div>
          )}

          {!loading && !error && (
            <>
              {/* TAB 1: OVERVIEW & IDENTITIES */}
              {activeTab === "overview" && (
                <div className="space-y-6">
                  {/* Channels & Identities */}
                  <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
                    <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                      <MessageCircle className="h-4 w-4" />
                      <span>{isAr ? "معرّفات القنوات الرقمية والتواصل" : "Channel Identities & Contact Info"}</span>
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                      {profile.phone && (
                        <div className="flex items-center gap-2.5 p-2.5 rounded-xl border border-border/80 bg-surface/50">
                          <Phone className="h-4 w-4 text-emerald-500 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-[11px] text-muted-foreground">{isAr ? "رقم الهاتف" : "Phone"}</div>
                            <div className="text-[13px] font-medium truncate" dir="ltr">{profile.phone}</div>
                          </div>
                        </div>
                      )}
                      {profile.email && (
                        <div className="flex items-center gap-2.5 p-2.5 rounded-xl border border-border/80 bg-surface/50">
                          <Mail className="h-4 w-4 text-blue-500 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-[11px] text-muted-foreground">{isAr ? "البريد الإلكتروني" : "Email"}</div>
                            <div className="text-[13px] font-medium truncate" dir="ltr">{profile.email}</div>
                          </div>
                        </div>
                      )}
                      {identities.map((item) => (
                        <div key={item.id} className="flex items-center gap-2.5 p-2.5 rounded-xl border border-border/80 bg-surface/50">
                          <ChannelIcon channel={item.channel} className="h-4 w-4 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-[11px] text-muted-foreground capitalize">{item.channel}</div>
                            <div className="text-[13px] font-medium truncate" dir="auto">{item.external_id}</div>
                          </div>
                        </div>
                      ))}
                      {!profile.phone && !profile.email && identities.length === 0 && (
                        <p className="text-[13px] text-muted-foreground italic col-span-2">
                          {isAr ? "لا توجد معرّفات قنوات مسجلة بعد." : "No channel identities recorded yet."}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Customer Tags */}
                  <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
                    <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                      <Tag className="h-4 w-4" />
                      <span>{isAr ? "وسوم العميل (Tags)" : "Customer Tags"}</span>
                    </h4>
                    <div className="flex flex-wrap gap-2 pt-1">
                      {tags.map((tag) => (
                        <span
                          key={tag.id || tag.name}
                          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[12px] font-medium bg-surface border border-border/80 text-foreground"
                        >
                          <span>{tag.name}</span>
                          <button
                            type="button"
                            onClick={() => handleRemoveTag(tag.name)}
                            title={isAr ? "حذف الوسم" : "Remove tag"}
                            className="hover:text-destructive text-muted-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                      {tags.length === 0 && (
                        <p className="text-[12.5px] text-muted-foreground italic">{isAr ? "لم تتم إضافة وسوم بعد." : "No tags yet."}</p>
                      )}
                    </div>
                    {/* Add Tag Form */}
                    <form onSubmit={handleAddTag} className="flex gap-2 pt-2">
                      <input
                        value={newTag}
                        onChange={(e) => setNewTag(e.target.value)}
                        placeholder={isAr ? "أضف وسماً (مثال: جملة، VIP، دفع عند الاستلام)…" : "Add tag (e.g. VIP, Wholesale)…"}
                        className="flex-1 h-8 rounded-lg border border-border bg-surface px-3 text-[12.5px] outline-none focus:ring-2 focus:ring-primary/40"
                      />
                      <button
                        type="submit"
                        disabled={addingTag || !newTag.trim()}
                        className="h-8 px-3 rounded-lg bg-primary text-primary-foreground text-[12px] font-semibold hover:opacity-90 disabled:opacity-50 flex items-center gap-1 transition-opacity"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        <span>{isAr ? "إضافة" : "Add"}</span>
                      </button>
                    </form>
                  </div>

                  {/* Staff Internal Notes */}
                  <div className="rounded-2xl border border-border bg-card p-4 space-y-3">
                    <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      <span>{isAr ? "الملاحظات الداخلية للموظفين" : "Internal Staff Notes"}</span>
                    </h4>

                    {/* Add note composer */}
                    <form onSubmit={handleAddNote} className="space-y-2">
                      <textarea
                        rows={2}
                        value={newNote}
                        onChange={(e) => setNewNote(e.target.value)}
                        placeholder={isAr ? "أضف ملاحظة خاصة بالعميل (مرئية للموظفين فقط)…" : "Add private note about this customer…"}
                        className="w-full rounded-xl border border-border bg-surface p-3 text-[12.5px] outline-none focus:ring-2 focus:ring-primary/40 resize-none"
                      />
                      <div className="flex justify-end">
                        <button
                          type="submit"
                          disabled={addingNote || !newNote.trim()}
                          className="h-8 px-3.5 rounded-lg bg-primary text-primary-foreground text-[12px] font-semibold hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5 transition-opacity"
                        >
                          <Send className="h-3 w-3" />
                          <span>{isAr ? "حفظ الملاحظة" : "Save Note"}</span>
                        </button>
                      </div>
                    </form>

                    {/* Notes List */}
                    <div className="space-y-2.5 pt-2">
                      {notes.map((note) => (
                        <div key={note.id} className="rounded-xl border border-border/80 bg-surface/50 p-3 text-[12.5px]">
                          <p className="text-foreground whitespace-pre-wrap">{note.body}</p>
                          <div className="text-[11px] text-muted-foreground mt-2 flex items-center justify-between">
                            <span>{formatDate(note.created_at, lang)}</span>
                            <span className="opacity-70">{isAr ? "ملاحظة موظف" : "Staff Note"}</span>
                          </div>
                        </div>
                      ))}
                      {notes.length === 0 && (
                        <p className="text-[12.5px] text-muted-foreground italic">{isAr ? "لا توجد ملاحظات داخلية مسجلة بعد." : "No internal notes yet."}</p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: ORDERS & INVOICES */}
              {activeTab === "orders" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wider">
                      {isAr ? `جميع الفواتير والمبيعات (${orders.length})` : `All Orders (${orders.length})`}
                    </h4>
                    <span className="text-[12px] text-muted-foreground font-medium">
                      {isAr ? "الإجمالي:" : "Total:"} <strong className="text-foreground">{formatCurrency(ltv)}</strong>
                    </span>
                  </div>

                  {orders.length === 0 ? (
                    <div className="py-12 text-center rounded-2xl border border-dashed border-border p-6 space-y-2">
                      <Receipt className="h-8 w-8 mx-auto text-muted-foreground/60" />
                      <div className="text-[14px] font-semibold text-foreground">{isAr ? "لا توجد طلبات مسجلة بعد" : "No orders found"}</div>
                      <p className="text-[12px] text-muted-foreground">{isAr ? "الطلبات والمبيعات التي تتم عبر الكاشير أو القنوات ستظهر هنا تلقائياً." : "Orders from POS or conversation channels will appear here."}</p>
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {orders.map((order) => (
                        <div
                          key={order.id}
                          className="rounded-xl border border-border bg-card p-4 hover:border-primary/40 transition-colors space-y-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-[14px] font-bold text-foreground">
                                  #{order.number || String(order.id).slice(0, 8)}
                                </span>
                                <Badge tone={order.status === "completed" || order.status === "paid" ? "success" : "muted"}>
                                  {order.status}
                                </Badge>
                              </div>
                              <div className="text-[11.5px] text-muted-foreground mt-1 flex items-center gap-2">
                                <Calendar className="h-3.5 w-3.5" />
                                <span>{formatDate(order.created_at, lang)}</span>
                              </div>
                            </div>
                            <div className="text-right">
                              <div className="text-[15px] font-bold text-foreground tabular-nums">
                                {formatCurrency(Number(order.grand_total || order.total || 0))}
                              </div>
                              <div className="text-[11px] text-muted-foreground">
                                {order.items_count ? `${order.items_count} ${isAr ? "منتجات" : "items"}` : ""}
                              </div>
                            </div>
                          </div>

                          {/* Line items if available */}
                          {order.items && order.items.length > 0 && (
                            <div className="rounded-lg bg-surface/60 p-2.5 space-y-1 text-[12px]">
                              {order.items.map((it, idx) => (
                                <div key={idx} className="flex justify-between text-muted-foreground">
                                  <span>{it.quantity}x {it.name || it.product_name}</span>
                                  <span className="tabular-nums font-medium text-foreground">{formatCurrency(Number(it.total || 0))}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: ACTIVITY TIMELINE */}
              {activeTab === "timeline" && (
                <div className="space-y-4">
                  <h4 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wider">
                    {isAr ? "سجل التفاعلات والأحداث" : "Activity Timeline"}
                  </h4>

                  {timeline.length === 0 ? (
                    <p className="text-[13px] text-muted-foreground italic text-center py-10">
                      {isAr ? "لا توجد أنشطة مسجلة بعد لهذا العميل." : "No recorded activity yet."}
                    </p>
                  ) : (
                    <div className="relative border-s-2 border-border/80 ms-3 space-y-4 ps-4">
                      {timeline.map((event, index) => {
                        const Icon = EVENT_ICONS[event.kind] || Clock;
                        return (
                          <div key={`${event.kind}-${event.ref_id || event.at}-${index}`} className="relative group">
                            {/* Dot on line */}
                            <span className="absolute -start-[25px] top-1 h-6 w-6 rounded-full bg-card border-2 border-primary text-primary grid place-items-center shadow-xs">
                              <Icon className="h-3 w-3" />
                            </span>
                            <div className="rounded-xl border border-border/80 bg-card p-3 shadow-2xs hover:border-border transition-colors">
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-[13px] font-semibold text-foreground">{event.title || event.kind}</span>
                                <span className="text-[11px] text-muted-foreground tabular-nums">{formatDate(event.at, lang)}</span>
                              </div>
                              {event.subtitle && (
                                <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">{event.subtitle}</p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 4: INSIGHTS & HABITS */}
              {activeTab === "insights" && (
                <div className="space-y-4">
                  <div className="rounded-2xl border border-border bg-gradient-to-br from-primary/5 via-card to-card p-5 space-y-3">
                    <div className="flex items-center gap-2 text-primary font-bold text-[14px]">
                      <Sparkles className="h-4 w-4" />
                      <span>{isAr ? "تحليل الذكاء وسلوك الشراء للعميل" : "AI Customer Profile & Buying Habits"}</span>
                    </div>
                    <p className="text-[13px] text-foreground leading-relaxed">
                      {isVip
                        ? (isAr ? "عميل ذو قيمة عالية (VIP). يكرر الشراء ويفضل التعامل السريع، ولديه متوسط سلة مشتريات ممتاز." : "High-value VIP customer with strong repeat purchases and high average order value.")
                        : ordersCount > 0
                        ? (isAr ? "عميل منتظم لديه طلبات سابقة. يمكن تقديم عروض ترويجية مخصصة لرفع قيمة السلة." : "Regular customer with recorded purchases. Good candidate for loyalty promotions.")
                        : (isAr ? "عميل محتمل أو جهة اتصال جديدة لم تسجل طلبات بعد." : "Prospect or new contact with no completed purchases yet.")}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-[13px]">
                    <div className="p-3.5 rounded-xl border border-border bg-card">
                      <div className="text-[11.5px] text-muted-foreground">{isAr ? "القناة المفضلة" : "Preferred Channel"}</div>
                      <div className="text-[14px] font-bold text-foreground mt-1 flex items-center gap-2">
                        {identities[0] ? (
                          <>
                            <ChannelIcon channel={identities[0].channel} className="h-4 w-4" />
                            <span className="capitalize">{identities[0].channel}</span>
                          </>
                        ) : profile.phone ? (
                          <span>WhatsApp</span>
                        ) : (
                          <span>POS / Direct</span>
                        )}
                      </div>
                    </div>

                    <div className="p-3.5 rounded-xl border border-border bg-card">
                      <div className="text-[11.5px] text-muted-foreground">{isAr ? "معدل تكرار الشراء" : "Purchase Frequency"}</div>
                      <div className="text-[14px] font-bold text-foreground mt-1">
                        {ordersCount >= 3 ? (isAr ? "مرتفع (عميل دائم)" : "High (Loyal)") : ordersCount > 0 ? (isAr ? "متوسط" : "Moderate") : (isAr ? "أول مرة" : "First time")}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
