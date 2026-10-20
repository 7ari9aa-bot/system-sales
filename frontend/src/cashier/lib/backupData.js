// النسخ الاحتياطي: تجميع بيانات النظام في ملف واحد + سجل النسخ المحفوظة.

import { allVariants, customers, invoices, products, suppliers } from "@/cashier/lib/mockData";
import { exchangeRecords, returnRecords } from "@/cashier/lib/opsData";
import { purchaseOrders } from "@/cashier/lib/purchasesData";
import { expenseRows, shiftRecords, supplierReturnRecords } from "@/cashier/lib/storeOpsData";

export function buildBackupPayload() {
  return {
    app: "بوتيك النخبة",
    version: "1.0",
    exported_at: new Date().toISOString(),
    tables: {
      products,
      variants: allVariants,
      customers,
      suppliers,
      invoices,
      returns: returnRecords,
      exchanges: exchangeRecords,
      purchase_orders: purchaseOrders,
      supplier_returns: supplierReturnRecords,
      expenses: expenseRows,
      shifts: shiftRecords,
    },
  };
}

export const BACKUP_SIZE_LABEL = `${(JSON.stringify(buildBackupPayload()).length / 1024).toFixed(1)} كيلوبايت`;

export const backupTableCounts = [
  { key: "products", label: "المنتجات", count: products.length },
  { key: "variants", label: "الألوان والمقاسات", count: allVariants.length },
  { key: "invoices", label: "فواتير المبيعات", count: invoices.length },
  { key: "returns", label: "المرتجعات والاستبدال", count: returnRecords.length + exchangeRecords.length },
  { key: "purchases", label: "فواتير التوريد", count: purchaseOrders.length },
  { key: "supplier_returns", label: "مرتجعات الموردين", count: supplierReturnRecords.length },
  { key: "expenses", label: "المصروفات", count: expenseRows.length },
  { key: "shifts", label: "الورديات", count: shiftRecords.length },
  { key: "customers", label: "العملاء", count: customers.length },
  { key: "suppliers", label: "الموردون", count: suppliers.length },
];

export const BACKUP_TOTAL_RECORDS = backupTableCounts.reduce((s, t) => s + t.count, 0);

export const BACKUP_SCHEDULES = [
  { key: "daily", label: "كل يوم ٨ صباحًا" },
  { key: "weekly", label: "كل يوم أحد" },
  { key: "monthly", label: "أول كل شهر" },
  { key: "manual", label: "بدون جدولة (يدوي فقط)" },
];

export const backupRecords = [
  {
    id: "bk-1",
    number: "BK-2026-0042",
    date: "2026-10-19T08:00:00",
    type: "auto",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "النظام — تلقائي",
    note: "نسخة الصباح قبل فتح المحل",
    restoredAt: null,
  },
  {
    id: "bk-2",
    number: "BK-2026-0041",
    date: "2026-10-18T08:00:00",
    type: "auto",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "النظام — تلقائي",
    note: "نسخة يومية",
    restoredAt: null,
  },
  {
    id: "bk-3",
    number: "BK-2026-0040",
    date: "2026-10-18T21:45:00",
    type: "manual",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "منى عبد الله",
    note: "قبل تعديل أسعار التصنيفات",
    restoredAt: "2026-10-18T22:10:00",
  },
  {
    id: "bk-4",
    number: "BK-2026-0039",
    date: "2026-10-12T08:00:00",
    type: "auto",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "النظام — تلقائي",
    note: "نسخة أسبوعية",
    restoredAt: null,
  },
  {
    id: "bk-5",
    number: "BK-2026-0038",
    date: "2026-10-05T08:00:00",
    type: "auto",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "النظام — تلقائي",
    note: "نسخة أسبوعية",
    restoredAt: null,
  },
  {
    id: "bk-6",
    number: "BK-2026-0037",
    date: "2026-10-01T08:00:00",
    type: "auto",
    size: BACKUP_SIZE_LABEL,
    records: BACKUP_TOTAL_RECORDS,
    status: "completed",
    createdBy: "النظام — تلقائي",
    note: "نسخة أول الشهر",
    restoredAt: null,
  },
];