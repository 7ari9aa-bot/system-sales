/**
 * معاينة اللصق قبل ما يتبعت: نفس فكرة مركز الاستيراد، بس على النص اللي في الحافظة.
 *
 * القواعد هنا للعرض الفوري بس (عناوين مفهومة؟ اسم موجود؟ سعر رقم؟ SKU مكرر في اللصق؟).
 * الحكم النهائي للباك إند: الصفوف بتبقى جلسة استيراد وبتتراجع بنفس تحقق الملفات.
 */

const COLUMNS = [
  { key: "title", label: "اسم المنتج", aliases: ["title", "name", "productname", "اسمالمنتج", "الاسم", "المنتج", "الصنف"] },
  { key: "sku", label: "SKU", aliases: ["sku", "itemcode", "code", "كودالصنف", "كود"] },
  { key: "price", label: "السعر", aliases: ["price", "sellprice", "saleprice", "السعر", "سعر", "سعرالبيع"] },
  { key: "color", label: "اللون", aliases: ["color", "colour", "اللون", "لون"] },
  { key: "size", label: "المقاس", aliases: ["size", "المقاس", "مقاس"] },
  { key: "quantity", label: "الكمية", aliases: ["quantity", "qty", "stock", "onhand", "الكمية", "كمية", "الرصيد"] },
  { key: "category", label: "التصنيف", aliases: ["category", "type", "التصنيف", "القسم"] },
  { key: "brand", label: "الماركة", aliases: ["brand", "vendor", "الماركة"] },
  { key: "season", label: "الموسم", aliases: ["season", "collection", "الموسم", "موسم"] },
  { key: "material", label: "الخامة", aliases: ["material", "fabric", "الخامة", "خامة", "القماش"] },
  { key: "barcode", label: "الباركود", aliases: ["barcode", "ean", "الباركود", "باركود"] },
];

export const PASTE_COLUMN_LABELS = COLUMNS.map((c) => c.label);

const norm = (v) => String(v ?? "").trim().toLowerCase().replace(/[\s_\-.]/g, "");

function keyOf(header) {
  const h = norm(header);
  return COLUMNS.find((c) => c.aliases.some((a) => norm(a) === h))?.key ?? null;
}

export function delimiterOf(text = "") {
  const first = text.split(/\r?\n/).find((line) => line.trim()) ?? "";
  if (first.includes("\t")) return "\t";
  if (first.includes(";") && first.split(";").length > first.split(",").length) return ";";
  return ",";
}

/** الصفوف كما هي، مع أرقام سطورها الحقيقية عشان الرسالة تدل التاجر على السطر الغلط. */
function tableOf(text, delimiter) {
  return String(text ?? "")
    .split(/\r?\n/)
    .map((line, index) => ({ line: index + 1, cells: line.split(delimiter).map((c) => c.trim()) }))
    .filter((row) => row.cells.some(Boolean));
}

const isNumber = (v) => /^\d+(\.\d{1,2})?$/.test(String(v ?? "").trim());

/**
 * نتيجة القراءة: أعمدة مفهومة، صفوف جاهزة للمعاينة، ومشاكل بالعربي قبل أي رفع.
 * problems: [{line, message}]
 */
export function previewPaste(text) {
  const delimiter = delimiterOf(text);
  const table = tableOf(text, delimiter);
  const problems = [];
  if (table.length === 0) return { headers: [], rows: [], problems, delimiter, ready: false };

  const headerRow = table[0];
  const keys = headerRow.cells.map(keyOf);
  const understood = keys.filter(Boolean);
  if (understood.length === 0) {
    return {
      headers: headerRow.cells,
      rows: [],
      problems: [{ line: headerRow.line, message: "لا يوجد عمود مفهوم في أول سطر. لازم «اسم المنتج» أو «SKU» على الأقل" }],
      delimiter,
      ready: false,
    };
  }

  const index = Object.fromEntries(keys.map((k, i) => [k, i]).filter(([k]) => k));
  const rows = [];
  const seenSku = new Map();

  for (const row of table.slice(1)) {
    const value = (key) => (index[key] === undefined ? "" : (row.cells[index[key]] ?? ""));
    const item = {
      line: row.line,
      title: value("title"),
      sku: value("sku"),
      price: value("price"),
      color: value("color"),
      size: value("size"),
      quantity: value("quantity"),
      barcode: value("barcode"),
    };

    if (!item.title && !item.sku) {
      problems.push({ line: row.line, message: "السطر بلا اسم منتج ولا SKU" });
      continue;
    }
    if (item.price && !isNumber(item.price)) {
      problems.push({ line: row.line, message: `السعر «${item.price}» ليس رقماً` });
    }
    if (item.quantity && !/^\d+$/.test(item.quantity.trim())) {
      problems.push({ line: row.line, message: `الكمية «${item.quantity}» ليست عدداً صحيحاً` });
    }
    if (item.sku) {
      const key = item.sku.toLowerCase();
      if (seenSku.has(key)) {
        problems.push({ line: row.line, message: `SKU «${item.sku}» مكرر مع السطر ${seenSku.get(key)}` });
      } else {
        seenSku.set(key, row.line);
      }
    }
    rows.push(item);
  }

  return {
    headers: headerRow.cells,
    columns: understood,
    rows,
    problems,
    delimiter,
    ready: rows.length > 0,
    productCount: new Set(rows.map((r) => r.title || r.sku).filter(Boolean)).size,
  };
}
