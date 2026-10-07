import React from "react";
import { ExternalLink, Globe, Package, RefreshCw, Rocket, Store } from "lucide-react";
import { PageHeader, SectionCard, Badge } from "@/components/dashboard/ui";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";

/**
 * «My Website» (§206): the section that receives the external Website
 * Platform. The merchant picks a design, provisions the website, opens the
 * Studio via SSO, and publishes. Products come from this tenant's catalog
 * automatically — no product copies, only references.
 */

const WP_TOKEN_KEY = "wp_token";

function formatDate(value) {
  if (!value) return "—";
  try { return new Date(value).toLocaleString(); } catch { return value; }
}

export default function Website() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";

  const [overview, setOverview] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState("");
  const [message, setMessage] = React.useState(null);
  const [selectedTemplate, setSelectedTemplate] = React.useState("");
  const [products, setProducts] = React.useState(null);
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.allSettled([api("/website/overview"), api("/website/products-count")]).then(([ov, pc]) => {
      if (!alive) return;
      if (ov.status === "fulfilled") setOverview(ov.value);
      else setMessage({ kind: "err", text: ov.reason?.message || (isAr ? "تعذر تحميل حالة الموقع" : "Could not load website status") });
      if (pc.status === "fulfilled") setProducts(pc.value?.publishedProducts ?? 0);
    }).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [attempt, isAr]);

  const provision = async (templateId) => {
    setBusy("provision");
    setMessage(null);
    try {
      const result = await api("/website/provision", { method: "POST", body: JSON.stringify({ template_id: templateId }) });
      setOverview({ provisioned: true, website: result.website });
      setSelectedTemplate("");
      setMessage({ kind: "ok", text: isAr ? "تم إنشاء الموقع بنجاح — افتح البيلدر لتخصيصه" : "Website created — open the builder to customize" });
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    } finally {
      setBusy("");
    }
  };

  const openBuilder = async () => {
    setBusy("sso");
    setMessage(null);
    try {
      const session = await api("/website/session", { method: "POST", body: JSON.stringify({}) });
      localStorage.setItem(WP_TOKEN_KEY, session.token);
      window.open(session.studioUrl, "_blank", "noopener");
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    } finally {
      setBusy("");
    }
  };

  const publish = async () => {
    setBusy("publish");
    setMessage(null);
    try {
      const result = await api("/website/publish", { method: "POST", body: JSON.stringify({}) });
      if (result.ok) {
        setMessage({ kind: "ok", text: isAr ? "تم النشر — الموقع الحي متحدث الآن" : "Published — the live site is updated" });
        setAttempt((n) => n + 1);
      } else {
        setMessage({ kind: "err", text: result.message || (isAr ? "تعذر النشر" : "Publish failed") });
      }
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    } finally {
      setBusy("");
    }
  };

  const website = overview?.website;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav.website")}
        subtitle={isAr ? "موقع متجرك — اختر التصميم، خصصه، وانشره. منتجاتك من الكتالوج تظهر عليه تلقائيًا." : "Your store website — pick a design, customize it, publish. Your catalog products appear automatically."}
      />

      {message ? (
        <div className={message.kind === "ok" ? "rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800" : "rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"}>
          {message.text}
        </div>
      ) : null}

      {loading ? (
        <SectionCard><div className="animate-pulse space-y-3"><div className="h-4 w-1/3 rounded bg-muted" /><div className="h-24 rounded bg-muted" /></div></SectionCard>
      ) : overview?.provisioned ? (
        <>
          <SectionCard title={isAr ? "حالة الموقع" : "Website status"}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex items-center gap-3">
                <Globe className="h-5 w-5 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{website?.name}</div>
                  <div className="text-xs text-muted-foreground">/{website?.slug}</div>
                </div>
                <Badge variant={website?.activeReleaseId ? "default" : "secondary"} className="ms-auto">
                  {website?.activeReleaseId ? (isAr ? "منشور" : "Published") : (isAr ? "غير منشور" : "Draft")}
                </Badge>
              </div>
              <div className="flex items-center gap-3">
                <RefreshCw className="h-5 w-5 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{isAr ? "آخر نشر" : "Last publish"}</div>
                  <div className="text-xs text-muted-foreground">{formatDate(website?.lastPublishedAt)}</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Package className="h-5 w-5 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{isAr ? "منتجات منشورة" : "Published products"}</div>
                  <div className="text-xs text-muted-foreground">{products ?? "—"} {isAr ? "منتج يظهر على الموقع تلقائيًا" : "products shown automatically"}</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Store className="h-5 w-5 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">{isAr ? "الخطة" : "Plan"}</div>
                  <div className="text-xs text-muted-foreground">{overview?.usage?.plan ?? "free"}</div>
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={openBuilder} disabled={busy === "sso"} className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                <ExternalLink className="h-4 w-4" />{busy === "sso" ? (isAr ? "جارٍ الفتح…" : "Opening…") : (isAr ? "فتح البيلدر" : "Open builder")}
              </button>
              <button onClick={publish} disabled={busy === "publish"} className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50">
                <Rocket className="h-4 w-4" />{busy === "publish" ? (isAr ? "جارٍ النشر…" : "Publishing…") : (isAr ? "نشر التحديثات" : "Publish updates")}
              </button>
              <button onClick={() => setAttempt((n) => n + 1)} className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent">
                <RefreshCw className="h-4 w-4" />{isAr ? "تحديث" : "Refresh"}
              </button>
              {website?.activeReleaseId ? (
                <a href={`https://wp-platform-hamedadel7744-9853.vercel.app/${website.slug}/`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent">
                  <Globe className="h-4 w-4" />{isAr ? "عرض الموقع" : "View live site"}
                </a>
              ) : null}
            </div>
          </SectionCard>
          <SectionCard title={isAr ? "منتجاتك على الموقع" : "Your products on the site"}>
            <p className="text-sm text-muted-foreground">
              {isAr
                ? "المنتجات المنشورة في كتالوج نظام المبيعات تظهر على الموقع تلقائيًا (ربط حي). أضف أو عدّل منتجاتك من صفحة المنتجات وستنعكس على الموقع بحسب سياسة التحديث."
                : "Products published in the Sales OS catalog appear on your website automatically (live binding). Manage them from the Products page."}
            </p>
          </SectionCard>
        </>
      ) : (
        <>
          <SectionCard title={isAr ? "اختر تصميم موقعك" : "Choose your website design"}>
            <p className="mb-4 text-sm text-muted-foreground">
              {isAr ? "كل تصميم جاهز بمحتوى تجريبي — تختاره فينشأ موقعك منه فورًا، وتقدر تخصص كل حاجة بعدها." : "Each design ships with demo content — pick one and your site is created instantly, fully customizable."}
            </p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {(overview?.templates ?? []).map((tpl) => (
                <div key={tpl.templateId} className={`rounded-xl border p-4 transition ${selectedTemplate === tpl.templateId ? "border-primary ring-2 ring-primary/30" : "hover:border-primary/40"}`}>
                  <div className="mb-3 flex h-24 items-center justify-center rounded-lg bg-gradient-to-br from-primary/10 to-primary/5">
                    <Globe className="h-8 w-8 text-primary/60" />
                  </div>
                  <div className="text-sm font-semibold">{tpl.name}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{tpl.description}</div>
                  <button
                    onClick={() => setSelectedTemplate(tpl.templateId)}
                    className="mt-3 w-full rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
                  >
                    {selectedTemplate === tpl.templateId ? (isAr ? "محدد ✓" : "Selected ✓") : (isAr ? "تحديد" : "Select")}
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={() => selectedTemplate && provision(selectedTemplate)}
              disabled={!selectedTemplate || busy === "provision"}
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Rocket className="h-4 w-4" />{busy === "provision" ? (isAr ? "جارٍ الإنشاء…" : "Creating…") : (isAr ? "إنشاء الموقع بهذا التصميم" : "Create website with this design")}
            </button>
          </SectionCard>
        </>
      )}
    </div>
  );
}
