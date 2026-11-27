/** جرد الفصحى: بيعدّ النصوص العامية الباقية في الواجهة، ملف ورا ملف.
 *
 *  الغرض إن تحويل الموقع كله لفصحى يبقى شغل مقاس مش إحساس: كل لفة بتقول كام نص
 *  باقي وفين، والرقم لازم ينزل. السكربت بيقرا بس، ومابيكتبش أي حاجة.
 *
 *  الكلمات القصيرة بتتقري ككلمة كاملة، لأن «هامش» فيها «مش» وهي فصحى سليمة —
 *  والعدّاد لازم يعدّ العامي الحقيقي بس، مش أي حرف جوه كلمة.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

/** كلمات عامية بتتقري لوحدها، مش جوه كلمة تانية. */
export const WORDS = [
  "اللي",
  "مش",
  "مفيش",
  "لسه",
  "ده",
  "دي",
  "دول",
  "دلوقتي",
  "إيه",
  "إزاي",
  "ازاي",
  "عشان",
  "كده",
  "بتاع",
  "بتاعة",
  "أوي",
  "برضه",
  "كويس",
  "يعني",
  "خلاص",
  "عايز",
  "عايزة",
  "كمان",
  "بص",
  "طب",
  "إحنا",
  "إنت",
  "معاك",
  "محتاج",
  "محتاجة",
  "النهارده",
  "بكرة",
  "امبارح",
  "إمتى",
  "امتى",
  "ليه",
  "فين",
  "مين",
  "حاجة",
  "بقى",
  "خلي",
];

/** تراكيب عامية بتتقري كجزء من الكلمة. */
export const PHRASES = [
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
  "بتشتغل",
  "بيشتغل",
  "بتكتب",
  "بيكتب",
  "بتظهر",
  "بيظهر",
  "مابي",
  "هيطلب",
  "هتطلب",
  "هتعمل",
  "هيعمل",
];

const STRING = /(["'`])((?:[^"'`\\]|\\.)*)\1/g;
const EDGE = "\\s(«»\"'.،:؛!؟\\-";

const wordPattern = (word) =>
  new RegExp(`(^|[${EDGE}])${word}($|[${EDGE}])`);

/** بيرجّع النصوص العربية اللي فيها علامة عامية. */
export function colloquialStrings(source) {
  const found = [];
  for (const match of source.matchAll(STRING)) {
    const body = match[2];
    if (!/[\u0600-\u06FF]/.test(body)) continue;
    const wordHit = WORDS.some((word) => wordPattern(word).test(body));
    const phraseHit = PHRASES.some((phrase) => body.includes(phrase));
    if (wordHit || phraseHit) found.push(body);
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
