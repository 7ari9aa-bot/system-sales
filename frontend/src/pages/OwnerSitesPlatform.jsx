import React, { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Badge, SectionCard } from "@/components/dashboard/ui";
import { cn } from "@/lib/utils";

/**
 * Owner console, "Websites" section: manages the Fihrist Sites platform.
 *
 * Deliberately absent: confirming a payment, deleting a site or a merchant. Those stay in the
 * platform's own console, where they ask for a payment reference / the typed site name.
 */
const PANELS = [
  { id: "purchases", ar: "الطلبات", en: "Purchases" },
  { id: "sites", ar: "المواقع", en: "Sites" },
  { id: "designs", ar: "التصاميم", en: "Designs" },
  { id: "limits", ar: "الحدود", en: "Limits" },
  { id: "legal", ar: "الصفحات القانونية", en: "Legal pages" },
  { id: "links", ar: "ربط فهرست", en: "Fihrist links" },
  { id: "audit", ar: "السجل", en: "Audit" },
];

const BASE = "/owner/sites-platform";
const INPUT = "w-full rounded-lg border border-border bg-background px-3 py-2 text-[13px]";
const BTN =
  "inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12.5px] font-medium hover:bg-surface disabled:opacity-50";

function when(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

const ORDER_TONE = { pending: "warning", confirmed: "success", cancelled: "muted" };

export default function OwnerSitesPlatform() {
  const { lang } = useI18n();
  const L = (ar, en) => (lang === "ar" ? ar : en);
  const [panel, setPanel] = useState("purchases");
  const [configured, setConfigured] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [edit, setEdit] = useState(null);

  const path = { purchases: "purchases", sites: "sites", designs: "designs", limits: "limits", legal: "legal", links: "fihrist-links", audit: "audit" }[panel];

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const status = await api(`${BASE}/status`);
      setConfigured(!!status?.configured);
      if (!status?.configured) {
        setRows([]);
        return;
      }
      const data = await api(`${BASE}/${path}`);
      setRows(Array.isArray(data?.items) ? data.items : []);
    } catch (err) {
      setError(err?.message || L("تعذر تحميل البيانات.", "Could not load the data."));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setEdit(null);
    setNotice("");
    load();
  }, [load]);

  async function act(key, call, okMessage) {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await call();
      setNotice(okMessage);
      setEdit(null);
      await load();
    } catch (err) {
      setError(err?.message || L("تعذر تنفيذ العملية.", "The action failed."));
    } finally {
      setBusy("");
    }
  }

  const patch = (url, body) => api(`${BASE}/${url}`, { method: "PATCH", body });

  function toggleSite(site) {
    const suspend = site.status !== "suspended";
    const msg = suspend
      ? L(`إيقاف موقع «${site.name}»؟ سيظهر للزوار كأنه غير موجود.`, `Suspend “${site.name}”? Visitors will see it as not found.`)
      : L(`إعادة تفعيل موقع «${site.name}»؟`, `Reactivate “${site.name}”?`);
    if (!window.confirm(msg)) return;
    act(`site:${site.id}`, () => patch(`sites/${site.id}`, { status: suspend ? "suspended" : "active" }), suspend ? L("تم إيقاف الموقع.", "Site suspended.") : L("تم تفعيل الموقع.", "Site reactivated."));
  }

  function saveDesign(design) {
    const price = Number(edit.price);
    if (!Number.isInteger(price) || price < 0) {
      setError(L("السعر لازم يكون رقم صحيح لا يقل عن صفر.", "Price must be a whole number, zero or more."));
      return;
    }
    act(`design:${design.key}`, () => patch(`designs/${design.key}`, { price_egp: price }), L("تم حفظ السعر.", "Price saved."));
  }

  function toggleListed(design) {
    act(`list:${design.key}`, () => patch(`designs/${design.key}`, { is_listed: !design.is_listed }), design.is_listed ? L("اتخفى من المعرض.", "Hidden from the gallery.") : L("ظهر في المعرض.", "Shown in the gallery."));
  }

  function saveLimit(limit) {
    const value = Number(edit.value);
    if (!Number.isInteger(value) || value < 0) {
      setError(L("الحد لازم يكون رقم صحيح لا يقل عن صفر.", "A limit must be a whole number, zero or more."));
      return;
    }
    act(`limit:${limit.key}`, () => api(`${BASE}/limits/${limit.key}`, { method: "PUT", body: { limit: value } }), L("تم حفظ الحد.", "Limit saved."));
  }

  function saveLegal(page) {
    const sections = edit.sections.filter((s) => s.title.trim() && s.body.trim());
    if (!edit.title.trim() || sections.length === 0) {
      setError(L("العنوان وقسم واحد على الأقل مطلوبين.", "A title and at least one section are required."));
      return;
    }
    if (!window.confirm(L("الحفظ يرجّع الصفحة مسودة لحد ما تنشرها. متابعة؟", "Saving returns the page to draft until you publish it. Continue?"))) return;
    act(
      `legal:${page.slug}`,
      () => api(`${BASE}/legal/${page.slug}`, { method: "PUT", body: { title: edit.title.trim(), summary: edit.summary.trim(), sections } }),
      L("تم الحفظ، والصفحة الآن مسودة.", "Saved. The page is now a draft.")
    );
  }

  function publishLegal(page, publish) {
    if (publish && !window.confirm(L("هل راجعت الصفحة قانونياً؟ النشر يشيل علامة «مسودة» عنها.", "Have you had this page reviewed? Publishing removes its draft notice."))) return;
    act(`pub:${page.slug}`, () => api(`${BASE}/legal/${page.slug}/publish`, { method: "POST", body: { publish } }), publish ? L("تم النشر.", "Published.") : L("رجعت مسودة.", "Back to draft."));
  }

  function toggleSync(link) {
    act(`sync:${link.site_id}`, () => patch(`fihrist-links/${link.site_id}`, { sync_enabled: !link.sync_enabled }), link.sync_enabled ? L("اتوقفت المزامنة.", "Sync paused.") : L("اتفعلت المزامنة.", "Sync resumed."));
  }

  const th = "py-2.5 text-start font-medium";
  const td = "py-2.5 pe-3 align-top";

  function table(head, body) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              {head.map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    );
  }

  const empty = <p className="py-6 text-center text-[13px] text-muted-foreground">{L("لا توجد بيانات.", "Nothing here yet.")}</p>;

  function render() {
    if (rows.length === 0) return empty;
    if (panel === "purchases")
      return table(
        [L("الموقع", "Site"), L("التصميم", "Design"), L("المبلغ", "Amount"), L("الحالة", "Status"), L("مرجع الدفع", "Payment ref"), L("التاريخ", "Date")],
        rows.map((o) => (
          <tr key={o.id} className="border-b border-border/60">
            <td className={td}><div className="font-medium">{o.site_name}</div><div className="text-[11px] text-muted-foreground" dir="ltr">{o.slug}</div></td>
            <td className={td}>{o.design}</td>
            <td className={td}>{Number(o.amount_egp).toLocaleString()} {L("ج.م", "EGP")}</td>
            <td className={td}><Badge tone={ORDER_TONE[o.status] || "muted"}>{o.status}</Badge></td>
            <td className={td} dir="ltr">{o.payment_ref || "—"}</td>
            <td className={td}>{when(o.created_at)}</td>
          </tr>
        ))
      );
    if (panel === "sites")
      return table(
        [L("الموقع", "Site"), L("التصميم", "Design"), L("الحالة", "Status"), L("منتجات", "Products"), L("طلبات", "Orders"), L("مفتوحة", "Open"), L("الإيراد (ج.م)", "Revenue (EGP)"), L("زيارات 30 يوم", "Views 30d"), L("كوبونات نشطة", "Active coupons"), L("رسائل", "Messages"), ""],
        rows.map((s) => (
          <tr key={s.id} className="border-b border-border/60">
            <td className={td}><div className="font-medium">{s.name}</div><a className="text-[11px] text-primary" dir="ltr" href={`https://${s.slug}.sites.fihrist.world`} target="_blank" rel="noreferrer noopener">{s.slug}</a></td>
            <td className={td}>{s.design}</td>
            <td className={td}><Badge tone={s.status === "active" ? "success" : "warning"}>{s.status}</Badge></td>
            <td className={td}>{s.products}</td>
            <td className={td}>{s.orders}</td>
            <td className={td}>{s.open_orders ?? 0}</td>
            <td className={td} title={s.revenue_capped ? L("على الأقل: الموقع تجاوز حد الحساب", "At least: the site is past the calculation cap") : undefined}>{Number(s.revenue ?? 0).toLocaleString()}{s.revenue_capped ? "+" : ""}</td>
            <td className={td} title={s.views_capped ? L("على الأقل: الموقع تجاوز حد الحساب", "At least: the site is past the calculation cap") : undefined}>{Number(s.views_30d ?? 0).toLocaleString()}{s.views_capped ? "+" : ""}</td>
            <td className={td}>{s.coupons}</td>
            <td className={td}>{s.messages}</td>
            <td className={cn(td, "text-end")}>
              <button type="button" className={BTN} disabled={busy === `site:${s.id}`} onClick={() => toggleSite(s)}>
                {s.status === "suspended" ? L("تفعيل", "Reactivate") : L("إيقاف", "Suspend")}
              </button>
            </td>
          </tr>
        ))
      );
    if (panel === "designs")
      return table(
        [L("التصميم", "Design"), L("السعر (ج.م)", "Price (EGP)"), L("المعرض", "Gallery"), L("مواقع", "Sites"), ""],
        rows.map((d) => (
          <tr key={d.key} className="border-b border-border/60">
            <td className={td}><div className="font-medium">{d.name}</div><div className="text-[11px] text-muted-foreground" dir="ltr">{d.key}</div></td>
            <td className={td}>
              {edit?.key === d.key ? (
                <input className={cn(INPUT, "w-28")} type="number" min="0" value={edit.price} onChange={(e) => setEdit({ ...edit, price: e.target.value })} />
              ) : (
                Number(d.price_egp).toLocaleString()
              )}
            </td>
            <td className={td}><Badge tone={d.is_listed ? "success" : "muted"}>{d.is_listed ? L("ظاهر", "Listed") : L("مخفي", "Hidden")}</Badge>{!d.is_live && <Badge tone="warning">{L("غير منشور", "Not live")}</Badge>}</td>
            <td className={td}>{d.sites}</td>
            <td className={cn(td, "text-end whitespace-nowrap")}>
              {edit?.key === d.key ? (
                <>
                  <button type="button" className={BTN} disabled={busy === `design:${d.key}`} onClick={() => saveDesign(d)}>{L("حفظ", "Save")}</button>{" "}
                  <button type="button" className={BTN} onClick={() => setEdit(null)}>{L("إلغاء", "Cancel")}</button>
                </>
              ) : (
                <>
                  <button type="button" className={BTN} onClick={() => setEdit({ key: d.key, price: String(d.price_egp) })}>{L("تعديل السعر", "Edit price")}</button>{" "}
                  <button type="button" className={BTN} disabled={busy === `list:${d.key}`} onClick={() => toggleListed(d)}>{d.is_listed ? L("إخفاء", "Hide") : L("إظهار", "Show")}</button>
                </>
              )}
            </td>
          </tr>
        ))
      );
    if (panel === "limits")
      return table(
        [L("الحد", "Limit"), L("القيمة", "Value"), ""],
        rows.map((l) => (
          <tr key={l.key} className="border-b border-border/60">
            <td className={td}><div className="font-medium">{l.label || l.key}</div><div className="text-[11px] text-muted-foreground" dir="ltr">{l.key}</div></td>
            <td className={td}>
              {edit?.key === l.key ? (
                <input className={cn(INPUT, "w-32")} type="number" min="0" value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />
              ) : (
                Number(l.value).toLocaleString()
              )}
            </td>
            <td className={cn(td, "text-end whitespace-nowrap")}>
              {edit?.key === l.key ? (
                <>
                  <button type="button" className={BTN} disabled={busy === `limit:${l.key}`} onClick={() => saveLimit(l)}>{L("حفظ", "Save")}</button>{" "}
                  <button type="button" className={BTN} onClick={() => setEdit(null)}>{L("إلغاء", "Cancel")}</button>
                </>
              ) : (
                <button type="button" className={BTN} onClick={() => setEdit({ key: l.key, value: String(l.value) })}>{L("تعديل", "Edit")}</button>
              )}
            </td>
          </tr>
        ))
      );
    if (panel === "legal")
      return (
        <div className="space-y-3">
          {rows.map((p) => (
            <div key={p.slug} className="rounded-xl border border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium">{p.title}</span>{" "}
                  <Badge tone={p.is_draft ? "warning" : "success"}>{p.is_draft ? L("مسودة", "Draft") : L("منشورة", "Published")}</Badge>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{(p.sections || []).length} {L("أقسام", "sections")} · {when(p.updated_at)}</div>
                </div>
                {edit?.slug !== p.slug && (
                  <div className="flex gap-2">
                    <button type="button" className={BTN} onClick={() => setEdit({ slug: p.slug, title: p.title, summary: p.summary || "", sections: (p.sections || []).map((s) => ({ title: s.title || "", body: s.body || "" })) })}>{L("تعديل", "Edit")}</button>
                    <button type="button" className={BTN} disabled={busy === `pub:${p.slug}`} onClick={() => publishLegal(p, p.is_draft)}>{p.is_draft ? L("نشر", "Publish") : L("إرجاع لمسودة", "Unpublish")}</button>
                  </div>
                )}
              </div>
              {edit?.slug === p.slug && (
                <div className="mt-3 space-y-2">
                  <input className={INPUT} value={edit.title} maxLength={120} onChange={(e) => setEdit({ ...edit, title: e.target.value })} placeholder={L("العنوان", "Title")} />
                  <input className={INPUT} value={edit.summary} maxLength={400} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} placeholder={L("ملخص", "Summary")} />
                  {edit.sections.map((s, i) => (
                    <div key={i} className="rounded-lg border border-border/70 p-2">
                      <div className="flex gap-2">
                        <input className={INPUT} value={s.title} maxLength={160} onChange={(e) => setEdit({ ...edit, sections: edit.sections.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} placeholder={L("عنوان القسم", "Section title")} />
                        <button type="button" className={BTN} aria-label={L("حذف القسم", "Remove section")} disabled={edit.sections.length <= 1} onClick={() => setEdit({ ...edit, sections: edit.sections.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>
                      </div>
                      <textarea className={cn(INPUT, "mt-2 min-h-[90px]")} value={s.body} maxLength={6000} onChange={(e) => setEdit({ ...edit, sections: edit.sections.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)) })} placeholder={L("نص القسم", "Section text")} />
                    </div>
                  ))}
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={BTN} disabled={edit.sections.length >= 40} onClick={() => setEdit({ ...edit, sections: [...edit.sections, { title: "", body: "" }] })}><Plus className="h-4 w-4" />{L("قسم جديد", "Add section")}</button>
                    <button type="button" className={BTN} disabled={busy === `legal:${p.slug}`} onClick={() => saveLegal(p)}>{L("حفظ كمسودة", "Save as draft")}</button>
                    <button type="button" className={BTN} onClick={() => setEdit(null)}>{L("إلغاء", "Cancel")}</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      );
    if (panel === "links")
      return table(
        [L("الموقع", "Site"), L("المفتاح", "Key"), L("آخر مزامنة", "Last sync"), L("الحالة", "Result"), L("منتجات", "Products"), L("المزامنة", "Sync"), ""],
        rows.map((k) => (
          <tr key={k.site_id} className="border-b border-border/60">
            <td className={td}>{k.site?.name || k.site_id}</td>
            <td className={td} dir="ltr">…{k.key_hint}</td>
            <td className={td}>{when(k.last_sync_at)}</td>
            <td className={td}>{k.last_sync_status ? <Badge tone={k.last_sync_status === "ok" ? "success" : "destructive"}>{k.last_sync_status}</Badge> : "—"}{k.last_sync_error && <div className="mt-1 max-w-[260px] text-[11px] text-destructive">{k.last_sync_error}</div>}</td>
            <td className={td}>{k.last_sync_count ?? "—"}</td>
            <td className={td}><Badge tone={k.sync_enabled ? "success" : "warning"}>{k.sync_enabled ? L("شغالة", "On") : L("موقوفة", "Paused")}</Badge></td>
            <td className={cn(td, "text-end")}><button type="button" className={BTN} disabled={busy === `sync:${k.site_id}`} onClick={() => toggleSync(k)}>{k.sync_enabled ? L("إيقاف", "Pause") : L("استئناف", "Resume")}</button></td>
          </tr>
        ))
      );
    return table(
      [L("الإجراء", "Action"), L("الهدف", "Target"), L("بواسطة", "By"), L("التاريخ", "Date")],
      rows.map((a) => (
        <tr key={a.id} className="border-b border-border/60">
          <td className={td} dir="ltr">{a.action}</td>
          <td className={td} dir="ltr">{a.target || "—"}</td>
          <td className={td}>{a.actor || L("النظام (تلقائي)", "System (automatic)")}</td>
          <td className={td}>{when(a.created_at)}</td>
        </tr>
      ))
    );
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {PANELS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setPanel(item.id)}
            className={cn("rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors", panel === item.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-surface")}
          >
            {lang === "ar" ? item.ar : item.en}
          </button>
        ))}
        <button type="button" className={cn(BTN, "ms-auto")} onClick={load} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          {L("تحديث", "Refresh")}
        </button>
      </div>

      {error && <div role="alert" className="mb-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-[13px] text-destructive">{error}</div>}
      {notice && <div role="status" className="mb-3 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-[13px] text-success">{notice}</div>}

      {configured === false ? (
        <SectionCard title={L("نظام المواقع غير مربوط", "Sites platform not connected")}>
          <p className="text-[13px] leading-6 text-muted-foreground">
            {L(
              "القسم جاهز لكن مش متوصل بقاعدة بيانات منصة المواقع. أضف SITES_PLATFORM_SUPABASE_URL وSITES_PLATFORM_SERVICE_KEY في إعدادات الخادم (Northflank) وأعد التشغيل.",
              "The section is installed but not connected to the sites platform database. Set SITES_PLATFORM_SUPABASE_URL and SITES_PLATFORM_SERVICE_KEY on the server (Northflank) and restart."
            )}
          </p>
        </SectionCard>
      ) : (
        <SectionCard title={PANELS.find((p) => p.id === panel)[lang === "ar" ? "ar" : "en"]}>
          {loading && rows.length === 0 ? <p className="py-6 text-center text-[13px] text-muted-foreground">{L("جارٍ التحميل…", "Loading…")}</p> : render()}
          <p className="mt-4 border-t border-border pt-3 text-[11.5px] leading-5 text-muted-foreground">
            {L(
              "تأكيد الدفع وحذف المواقع والتجار يتم من كونسول منصة المواقع نفسه (owner.sites.fihrist.world) لأنه يطلب مرجع الدفع وكتابة اسم الموقع قبل التنفيذ.",
              "Confirming payments and deleting sites or merchants happens in the sites platform’s own console (owner.sites.fihrist.world), which asks for a payment reference and the typed site name first."
            )}
          </p>
        </SectionCard>
      )}
    </div>
  );
}
