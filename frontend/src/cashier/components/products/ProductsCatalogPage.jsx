import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { Archive, Pencil, Plus, RotateCcw, Search, Upload } from "lucide-react";
import { toast } from "sonner";
import { useBrands, useCategories } from "@/cashier/api/useCatalogWrite";
import { PAGE_SIZE, useCatalogPage, useSetProductStatus } from "@/cashier/api/useCatalogList";
import { useStockSeasons } from "@/cashier/api/useStock";
import { PRODUCT_STATUS, priceRangeLabel } from "@/cashier/lib/productRows";
import { fmtInt, fmtNumber } from "@/cashier/lib/format";

// صفحة المنتجات: سجل الكتالوج. المخزون له شاشته (أرصدة وحركات)، وهنا الموديلات نفسها:
// تبحث، تفلتر، تفتح للتعديل، تأرشف، أو ترجّع للبيع.

const PRIMARY =
  "inline-flex h-11 items-center gap-2 rounded-xl border border-[#E8761A] bg-[#E8761A] px-5 text-[14px] font-bold text-white shadow-[0_8px_20px_-10px_rgba(232,118,26,.8)] transition-colors hover:bg-[#D1650F] hover:border-[#D1650F] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";
const GHOST =
  "inline-flex h-11 items-center gap-2 rounded-xl border border-[#d9d4cd] bg-white px-4 text-[14px] font-semibold text-[#3a342d] transition-colors hover:border-[#E8761A] hover:text-[#E8761A]";
const FIELD =
  "h-11 rounded-xl border border-[#ddd7cf] bg-white px-3 text-[14px] text-[#2a2622] outline-none transition-[border-color,box-shadow] focus:border-[#E8761A] focus:shadow-[0_0_0_3px_rgba(232,118,26,.15)]";
const TH = "px-4 py-3 text-right text-[12px] font-semibold text-[#8a8277]";
const TD = "px-4 py-3 text-right text-[13px] text-[#3a342d] align-middle";

const STATUS_ORDER = ["", "active", "draft", "archived"];

export default function ProductsCatalogPage() {
  const [filters, setFilters] = useState({ term: "", categoryId: "", brandId: "", season: "", status: "active", sort: "newest" });
  const [page, setPage] = useState(0);
  const [confirming, setConfirming] = useState(null);
  // البحث بيتأخر شوية عشان كل حرف مايعملش طلب لوحده
  const [typed, setTyped] = useState("");
  const products = useCatalogPage({ ...filters, term: typed }, page);
  const categories = useCategories();
  const brands = useBrands();
  const seasons = useStockSeasons();
  const setStatus = useSetProductStatus();

  const rows = products.data?.rows ?? [];
  const total = products.data?.total ?? 0;
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = page * PAGE_SIZE + rows.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const categoryName = useMemo(() => new Map((categories.data ?? []).map((c) => [String(c.id), c.name])), [categories.data]);
  const brandName = useMemo(() => new Map((brands.data ?? []).map((b) => [String(b.id), b.name])), [brands.data]);

  // أي تغيير في فلتر بيرجّعك لأول صفحة: الصفحة القديمة مش موجودة في النتيجة الجديدة.
  const patch = (next) => {
    setFilters((f) => ({ ...f, ...next }));
    setPage(0);
  };

  useEffect(() => {
    const id = setTimeout(() => {
      setTyped(filters.term);
      setPage(0);
    }, 300);
    return () => clearTimeout(id);
  }, [filters.term]);

  async function changeStatus(row, status) {
    if (confirming !== row.id) {
      setConfirming(row.id);
      return;
    }
    setConfirming(null);
    try {
      await setStatus.mutateAsync({ id: row.id, status });
      toast.success(status === "archived" ? `تم أرشفة «${row.title}» وخرج من قائمة البيع` : `تم رجوع «${row.title}» للبيع`);
    } catch (e) {
      toast.error(e?.message ?? "تعذّر تغيير حالة المنتج");
    }
  }

  return (
    <div className="-mx-2 -my-2 min-h-[calc(100vh-1rem)] bg-[#F4F1EC] px-6 py-6 text-[#3A342D] sm:-mx-3 sm:px-9 sm:py-8">
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-5">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-heading text-[26px] font-bold text-[#2a2622]">المنتجات</h1>
            <p className="mt-1 text-[13px] text-[#8a8277]">
              {fmtInt(total)} منتج مطابق · بتشوف {fmtInt(from)}–{fmtInt(to)} · صفحة {fmtInt(page + 1)} من {fmtInt(pages)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/products/new" className={PRIMARY}>
              <Plus className="h-4 w-4" /> إضافة منتج
            </Link>
            <Link to="/inventory/import" className={GHOST}>
              <Upload className="h-4 w-4" /> استيراد من Excel
            </Link>
          </div>
        </header>

        <div className="rounded-[18px] border border-[#e6e1da] bg-white p-4 shadow-[0_1px_2px_rgba(40,30,20,.05)] sm:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#a9a29a]" />
              <input
                value={filters.term}
                onChange={(e) => patch({ term: e.target.value })}
                placeholder="ابحث بالاسم أو الكود أو SKU"
                className={`${FIELD} w-full pr-9`}
                aria-label="بحث في المنتجات"
              />
            </div>
            <select value={filters.status} onChange={(e) => patch({ status: e.target.value })} className={FIELD} aria-label="الحالة">
              {STATUS_ORDER.map((value) => (
                <option key={value || "all"} value={value}>
                  {value ? PRODUCT_STATUS[value].label : "كل الحالات"}
                </option>
              ))}
            </select>
            <select value={filters.categoryId} onChange={(e) => patch({ categoryId: e.target.value })} className={FIELD} aria-label="التصنيف">
              <option value="">كل التصنيفات</option>
              {(categories.data ?? []).map((c) => (
                <option key={c.id} value={String(c.id)}>{c.name}</option>
              ))}
            </select>
            <select value={filters.brandId} onChange={(e) => patch({ brandId: e.target.value })} className={FIELD} aria-label="الماركة">
              <option value="">كل الماركات</option>
              {(brands.data ?? []).map((b) => (
                <option key={b.id} value={String(b.id)}>{b.name}</option>
              ))}
            </select>
            <select value={filters.season} onChange={(e) => patch({ season: e.target.value })} className={FIELD} aria-label="الموسم">
              <option value="">كل المواسم</option>
              {(seasons.data ?? []).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select value={filters.sort} onChange={(e) => patch({ sort: e.target.value })} className={FIELD} aria-label="الترتيب">
              <option value="newest">الأحدث أولًا</option>
              <option value="oldest">الأقدم أولًا</option>
              <option value="name">الاسم (أ – ي)</option>
              <option value="name_desc">الاسم (ي – أ)</option>
            </select>
          </div>
        </div>

        <div className="overflow-hidden rounded-[18px] border border-[#e6e1da] bg-white shadow-[0_1px_2px_rgba(40,30,20,.05)]">
          {products.isLoading && rows.length === 0 ? (
            <p className="p-8 text-center text-[13px] text-[#8a8277]">جاري تحميل المنتجات…</p>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center gap-3 p-10 text-center">
              <p className="text-[15px] font-semibold text-[#2a2622]">
                {total === 0 && !filters.term ? "لسه مفيش منتجات في الكتالوج" : "مفيش منتج مطابق للفلاتر"}
              </p>
              <p className="max-w-[420px] text-[13px] text-[#8a8277]">
                {total === 0 && !filters.term
                  ? "ابدأ بإضافة منتج واحد، أو استورد ملف Excel فيه منتجاتك كلها."
                  : "وسّع البحث أو شيل فلتر الحالة عشان تشوف المؤرشف والمسودة."}
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                <Link to="/products/new" className={PRIMARY}><Plus className="h-4 w-4" /> إضافة منتج</Link>
                <Link to="/inventory/import" className={GHOST}><Upload className="h-4 w-4" /> استيراد من Excel</Link>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse">
                <thead className="border-b border-[#eee9e2] bg-[#faf9f7]">
                  <tr>
                    <th className={TH}>المنتج</th>
                    <th className={TH}>التصنيف</th>
                    <th className={TH}>الماركة</th>
                    <th className={TH}>الموسم / الخامة</th>
                    <th className={TH}>التركيبات</th>
                    <th className={TH}>السعر</th>
                    <th className={TH}>الحالة</th>
                    <th className={TH}>إجراءات</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b border-[#f2eee9] last:border-b-0 hover:bg-[#fbfaf8]">
                      <td className={TD}>
                        <div className="flex items-center gap-3">
                          {row.imageUrl ? (
                            <img src={row.imageUrl} alt="" className="h-10 w-10 rounded-lg object-cover" />
                          ) : (
                            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#f4f1ec] text-[11px] text-[#a9a29a]">بلا صورة</span>
                          )}
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-[#2a2622]">{row.title || "بلا اسم"}</p>
                            <p className="truncate text-[11px] text-[#8a8277]">{row.skus[0] ?? row.slug}</p>
                          </div>
                        </div>
                      </td>
                      <td className={TD}>{categoryName.get(row.categoryId) ?? "—"}</td>
                      <td className={TD}>{brandName.get(row.brandId) ?? "—"}</td>
                      <td className={TD}>{[row.season, row.material].filter(Boolean).join(" / ") || "—"}</td>
                      <td className={`${TD} num`}>{fmtInt(row.variantCount)}</td>
                      <td className={`${TD} num`}>{priceRangeLabel(row, (n) => fmtNumber(n, Number.isInteger(n) ? 0 : 2))}</td>
                      <td className={TD}>
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${(PRODUCT_STATUS[row.status] ?? PRODUCT_STATUS.draft).tone}`}>
                          {(PRODUCT_STATUS[row.status] ?? PRODUCT_STATUS.draft).label}
                        </span>
                      </td>
                      <td className={TD}>
                        <div className="flex items-center gap-2">
                          <Link to={`/products/${row.id}/edit`} className="inline-flex items-center gap-1 rounded-lg border border-[#d9d4cd] px-2.5 py-1.5 text-[12px] font-semibold text-[#3a342d] hover:border-[#E8761A] hover:text-[#E8761A]">
                            <Pencil className="h-3.5 w-3.5" /> تعديل
                          </Link>
                          {row.status === "archived" ? (
                            <button type="button" onClick={() => changeStatus(row, "active")} className="inline-flex items-center gap-1 rounded-lg border border-[#bfe6cb] bg-[#eaf7ee] px-2.5 py-1.5 text-[12px] font-semibold text-[#1e7a3c] hover:border-[#1e7a3c]">
                              <RotateCcw className="h-3.5 w-3.5" /> {confirming === row.id ? "تأكيد الرجوع؟" : "رجّعه للبيع"}
                            </button>
                          ) : (
                            <button type="button" onClick={() => changeStatus(row, "archived")} className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[12px] font-semibold ${confirming === row.id ? "border-[#E8761A] bg-[#fff1e6] text-[#B45309]" : "border-[#d9d4cd] text-[#6b6358] hover:border-[#E8761A] hover:text-[#E8761A]"}`}>
                              <Archive className="h-3.5 w-3.5" /> {confirming === row.id ? "تأكيد الأرشفة؟" : "أرشفة"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#eee9e2] bg-[#faf9f7] px-4 py-3">
              <p className="text-[12px] text-[#8a8277]">
                {fmtInt(from)}–{fmtInt(to)} من {fmtInt(total)} منتج
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className={`${GHOST} disabled:cursor-not-allowed disabled:opacity-40`}
                >
                  السابق
                </button>
                <span className="text-[12px] font-semibold text-[#6b6358]">
                  صفحة {fmtInt(page + 1)} من {fmtInt(pages)}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!products.data?.hasMore}
                  className={`${GHOST} disabled:cursor-not-allowed disabled:opacity-40`}
                >
                  التالي
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
