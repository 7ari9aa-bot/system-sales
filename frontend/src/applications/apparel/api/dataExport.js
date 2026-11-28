/**
 * "Export my data": one JSON file holding what the backend has right now, table by table.
 * This is an EXPORT for the owner's own records, not a restorable backup (restores and scheduled
 * backups are run at platform level). Each table is fetched on its own so one failing table is
 * reported in the file and on screen instead of silently producing a file that looks complete.
 */
import { posApi } from "./posApi";

export const EXPORT_TABLES = [
  { key: "products", cap: 500, label: "المنتجات", load: () => posApi.products() },
  { key: "stock", cap: 1000, label: "أرصدة المخزون", load: () => posApi.stock("limit=1000") },
  { key: "stock_movements", cap: 500, label: "حركة المخزون", load: () => posApi.movements("limit=500") },
  { key: "suppliers", label: "الموردون", load: () => posApi.listSuppliers() },
  { key: "purchase_orders", label: "فواتير التوريد", load: () => posApi.listPurchaseOrders() },
  { key: "supplier_payments", label: "مدفوعات الموردين", load: () => posApi.listSupplierPayments() },
  { key: "supplier_returns", label: "مرتجعات الموردين", load: () => posApi.listSupplierReturns() },
  { key: "expenses", cap: 500, label: "المصروفات", load: () => posApi.listExpenses() },
  { key: "shifts", cap: 500, label: "الورديات", load: () => posApi.listSessions("limit=500") },
];

const asList = (res) => (Array.isArray(res) ? res : (res?.items ?? []));

/**
 * Fetch every table. Returns { payload, counts, failed, truncated } where `counts` is [{key,label,count}] for the
 * tables that loaded and `failed` lists the keys that did not (their rows are absent from `payload`).
 */
export async function collectExport({ tables = EXPORT_TABLES, now = () => new Date() } = {}) {
  const settled = await Promise.allSettled(tables.map((t) => t.load()));
  const data = {};
  const counts = [];
  const failed = [];
  const truncated = [];
  settled.forEach((res, i) => {
    const t = tables[i];
    if (res.status === "fulfilled") {
      const rows = asList(res.value);
      data[t.key] = rows;
      counts.push({ key: t.key, label: t.label, count: rows.length });
      // The API returns a bare list with no "there is more" flag, so a table that came back exactly at
      // the limit we asked for may have more rows behind it. Say so instead of calling the file complete.
      if (t.cap && rows.length >= t.cap) truncated.push({ key: t.key, label: t.label, cap: t.cap });
    } else {
      failed.push({ key: t.key, label: t.label });
    }
  });
  return {
    payload: { exported_at: now().toISOString(), tables: data, failed_tables: failed.map((f) => f.key), truncated_tables: truncated.map((t) => t.key) },
    counts,
    failed,
    truncated,
  };
}

export const totalRows = (counts) => counts.reduce((s, c) => s + c.count, 0);
