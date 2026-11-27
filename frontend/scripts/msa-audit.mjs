/** جرد الفصحى: بيعدّ النصوص العامية الباقية في الواجهة، ملف ورا ملف.
 *
 *  الغرض إن تحويل الموقع كله لفصحى يبقى شغل مقاس مش إحساس: كل لفة بتقول كام نص
 *  باقي وفين، والرقم لازم ينزل. السكربت بيقرا بس، ومابيكتبش أي حاجة.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/** علامات العامي المصري: أدوات وأفعال مفيش لها مكان في الفصحى. */
export const MARKERS = [
  "اللي",
  "مش ",
  "مفيش",
  "لسه",
  " ده",
  " دي ",
  "دلوقتي",
  "إيه",
  "عشان",
  "كده",
  "بتاع",
  "أوي",
  "برضه",
  "كويس",
  "يعني",
  "خلاص",
  "عايز",
  "كمان",
  "بص ",
  "طب ",
  "إحنا",
  "إنت ",
  "معاك",
  "محتاج",
  "النهارده",
  "بكرة",
  "بيتحسب",
  "بتتحسب",
  "بيتم",
  "بتتم",
  "هيحصل",
  "هتكون",
  "هيكون",
  "اتعمل",
  "اتكتب",
  "اتقفل",
  "جوّاها",
  "تاني ",
];

const STRING = /(["'`])((?:[^"'`\\]|\\.)*)\1/g;

/** بيرجّع النصوص العربية اللي فيها علامة عامية. */
export function colloquialStrings(source) {
  const found = [];
  for (const match of source.matchAll(STRING)) {
    const body = match[2];
    if (!/[\u0600-\u06FF]/.test(body)) continue;
    if (MARKERS.some((marker) => body.includes(marker))) found.push(body);
  }
  return found;
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === "dist") continue;
    const path = join(dir, entry);
    const info = statSync(path);
    if (info.isDirectory()) walk(path, out);
    else if (/\.(jsx?|tsx?)$/.test(entry) && !/\.test\./.test(entry)) out.push(path);
  }
  return out;
}

if (process.argv[1]?.endsWith("msa-audit.mjs")) {
  const root = process.argv[2] ?? "src";
  const rows = [];
  for (const file of walk(root)) {
    const hits = colloquialStrings(readFileSync(file, "utf8"));
    if (hits.length) rows.push([relative(root, file), hits.length]);
  }
  rows.sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((sum, [, n]) => sum + n, 0);
  for (const [file, n] of rows) console.log(String(n).padStart(5), file);
  console.log(`\n${total} نص عامي في ${rows.length} ملف`);
}
