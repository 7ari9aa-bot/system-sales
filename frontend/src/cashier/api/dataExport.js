/**
 * "Export my data": one JSON file holding what the backend has right now, table by table.
 * This is an EXPORT for the owner's own records, not a restorable backup (restores and scheduled
 * backups are run at platform level). Each table is fetched on its own so one failing table is
 * reported in the file and on screen instead of silently producing a file that looks complete.
 */
import { posApi } from "./posApi";

export const EXPORT_TABLES = [
  { key: "products", label: "المنتجات", load: () => posApi.products() },
  { key: "stock", label: "أرصدة المخزون", load: () => posApi.stock("limit=1000") },
  { key: "stock_movements", label: "حركة المخزون", load: () => posApi.movements("limit=500") },
  { key: "suppliers", label: "الموردون", load: () => posApi.listSuppliers() },
  { key: "purchase_orders", label: "فواتير التوريد", load: () => posApi.listPurchaseOrders() },
  { key: "supplier_payments", label: "مدفوعات الموردين", load: () => posApi.listSupplierPayments() },
  { key: "supplier_returns", label: "مرتجعات الموردين", load: () => posApi.listSupplierReturns() },
  { key: "expenses", label: "المصروفات", load: () => posApi.listExpenses() },
  { key: "shifts", label: "الورديات", load: () => posApi.listSessions("limit=500") },
];

const asList = (res) => (Array.isArray(res) ? res : (res?.items ?? []));

/**
 * Fetch every table. Returns { payload, counts, failed } where `counts` is [{key,label,count}] for the
 * tables that loaded and `failed` lists the keys that did not (their rows are absent from `payload`).
 */
export async function collectExport({ tables = EXPORT_TABLES, now = () => new Date() } = {}) {
  const settled = await Promise.allSettled(tables.map((t) => t.load()));
  const data = {};
  const counts = [];
  const failed = [];
  settled.forEach((res, i) => {
    const t = tables[i];
    if (res.status === "fulfilled") {
      const rows = asList(res.value);
      data[t.key] = rows;
      counts.push({ key: t.key, label: t.label, count: rows.length });
    } else {
      failed.push({ key: t.key, label: t.label });
    }
  });
  return {
    payload: { exported_at: now().toISOString(), tables: data, failed_tables: failed.map((f) => f.key) },
    counts,
    failed,
  };
}

export const totalRows = (counts) => counts.reduce((s, c) => s + c.count, 0);
