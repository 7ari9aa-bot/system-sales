// قراءة ملف Excel/CSV محلياً في المتصفح (بدون رفع لأي سيرفر) وتحويل أعمدته العربية إلى مفاتيح ثابتة.
import * as XLSX from "xlsx";

const HEADER_TO_KEY = {
  "اسم المنتج": "name",
  "التصنيف": "category",
  "العلامة التجارية": "brand",
  "اللون": "color",
  "المقاس": "size",
  sku: "sku",
  "الباركود": "barcode",
  "سعر الشراء": "buyPrice",
  "سعر البيع": "sellPrice",
  "الكمية": "stock",
};

const MAX_ROWS = 2000;
const MAX_BYTES = 5 * 1024 * 1024;

export async function readProductsFile(file) {
  if (file.size > MAX_BYTES) return { status: "error", details: "الملف أكبر من 5 ميجا.", rows: [] };
  const buffer = await file.arrayBuffer();
  const workbook = XLSX.read(buffer, { type: "array" });
  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  if (!sheet) return { status: "error", details: "الملف لا يحتوي على ورقة بيانات.", rows: [] };

  const raw = XLSX.utils.sheet_to_json(sheet, { defval: "" });
  const rows = raw.slice(0, MAX_ROWS).map((r) => {
    const out = {};
    Object.entries(r).forEach(([header, value]) => {
      const key = HEADER_TO_KEY[String(header).trim()] ?? HEADER_TO_KEY[String(header).trim().toLowerCase()];
      if (key) out[key] = value;
    });
    return out;
  });
  const known = rows.filter((r) => Object.keys(r).length > 0);
  if (known.length === 0) return { status: "error", details: "لم أجد أعمدة مطابقة للنموذج. نزّل النموذج وطابق أسماء الأعمدة.", rows: [] };
  return { status: "success", details: null, rows: known };
}
